# Invalid-runs diff review 1: FAIL (1 Blocker, 4 Major, 3 Nit)

**Range:** `59a2c8c..ebd74d9` on `invalid-runs`.
**Mode:** REVIEW, using the Zoom-Out and Implementation-Readiness standards, with Heilmeier as design context.
**How I reviewed:** read-only. I read the design, the full code diff, the tests, the fixture provenance, the validation and artifact records, and the Murphy diff. I did not run any tests or workloads. I did check the pinned compatibility digests: they match the files at HEAD and at `6f17c5f`.

**Verdict:** FAIL. One blocker remains.

## Blocker

**B1. G16/G17 reviewers no longer see all the evidence. This can produce a wrong `hard` or `wrong_fix` verdict without anyone noticing.**
- **Where:** `factory/fairness.py:93-94`, the `review(... {'case': c.case, 'attempts': c.work / folder} ...)` call that replaced the old evidence copy (old `fairness.py:42-56`).
- **What changed:** The old code did two things the new code does not:
  - It copied any attempt whose workspace sits outside `folder` into the review directory as `kept-try-N`. This covers the early-probe try that `AttemptSeries` reuses as G10 strong try 1 (`calibration.py:340-344`, with `source: "early_probe"`, workspace `early_probe/try-1`).
  - It copied the strong-calibrator transcripts, which hold the owner questions and answers.
- **Impact:**
  - The early probe is on by default, so in most G17 diagnoses at least one try's guard and `execution.json` are missing from `./attempts`.
  - The transcripts are missing, so the reviewer cannot establish `missing_info`.
  - The prompt still says "owner questions/answers and transcripts", and `verdict()` checks only labels. A reviewer can therefore label a fix it never saw as `wrong_fix`, and `diagnose` then sets `difficulty = "hard"`. That is a scientific verdict built on missing evidence, which is exactly the failure class this workstream exists to prevent.
  - Row 41's closure tests miss this because the fixture's attempt always lives inside `folder` and has no transcripts.
- **Fix:**
  - Pass every attempt workspace to `independent_review.review` as an input, including those outside `folder`, plus the matching `transcripts/strong-calibrator-{folder,early_probe}-*.jsonl`. These are digest-bound, so reuse stays safe.
  - Make `validate` fail if any try's workspace is absent from the inputs.
  - Add a regression test using an early-probe-sourced row.

## Major

**M1. The G17/G16 missing-fix path buys a replacement calibration that can never be reviewed.**
- **Where:** `factory/fairness.py:48-59`.
- **What happens:** Each gate attempt quarantines the results and calls `r.calibrate(...)`, which is paid. It then raises `InvalidInfra`, which uses up one of the two gate-journal attempts.
  - If the replacement also submits nothing (a real possibility on genuinely hard cases), attempt 2 buys a second replacement and then hits `InfrastructureExhausted`.
  - That second paid calibration is never reviewed. The journal blocks the same inputs from running again.
- **A further issue:** `tries=len(attempts)` re-authors every try from the first missing one onward. Valid submissions that come after a missing one are bought again. The design says "Do not re-run already valid solver submissions."
- **Fix:** After the replacement, go straight into review in the same attempt, without raising. Allow at most one replacement per unchanged evidence, recorded with the review receipt. Re-author only the unreviewable tries, not the valid ones after them.

**M2. G2 now needs every logged URL to be fetchable, and any failure skips the existing repair path.**
- **Where:** `factory/run.py:1638-1646` and `factory/freshness_retrieval.py:24-37`.
- **What happens:** Every structurally valid row is fetched, including unflagged ones. Any 401, 403, 429 or 5xx from GitHub or a doc host (common for non-browser urllib traffic), or any oversized page, raises `InvalidInfra`. Two identical attempts later the case is `infrastructure_exhausted`.
- **Why it matters:**
  - Retrying cannot help, because the inputs are the same.
  - The failure goes around `ensure_freshness`'s topup, which could have replaced the unreachable row with another search.
  - One bot-blocked page in a searcher's log therefore halts the case until diagnosis.
  - The tests patch only a 200 response or a blanket failure, so this availability risk has no test.
- **Fix (pick one):**
  - Treat a failed fetch of an unflagged row as that row's `evidence_incomplete` (not counted). `ensure_freshness` can then request a replacement search. Keep `InvalidInfra` only for flagged rows, where a verdict depends on the bytes.
  - Or record this in the design as an accepted limit and keep row 24's closure, but then open a D/Murphy row for it.

**M3. Murphy row 36 is marked closed, but its Fix column is not implemented as written.**
- **Where:** `docs/murphy-register.md:46`.
- **What's wrong:** The row's fix says "automatically reject exhausted candidates". The implementation (`admission.prototype` → `retry`) instead stops the whole case as `infrastructure_exhausted`, and the closing test asserts exactly that. Under `docs/ENGINEERING.md`, a row closes only when a test proves the entire row.
- **Fix:** Either implement candidate rejection on exhaustion, or change the row's Fix/Today text to the design's operational stop awaiting D diagnosis (citing the design section) before marking it closed.

**M4. A successful run does not reset the retry journal, so later deliberate reruns get one try instead of two.**
- **Where:** `bin/run_validity.py:102-104`.
- **What happens:** On success, only `running` is cleared; `invalid_attempts` stays where it was. Gates are re-entered fresh on every resume (`c.card['resume'] = {"fresh_gates": True ...}`). So a unit that failed once and then passed reaches `InfrastructureExhausted` on its next single transient failure.
- **Why it matters:** The design says completed units "may execute normally when deliberately requested again". A unit that already completed should not inherit a reduced allowance.
- **Fix:** Reset `invalid_attempts` to 0 when the run completes, or start each invocation's allowance fresh after a `completed` status.

## Nit

- **N1. Valid G6 cheat rejection discarded** (`factory/run.py:1953`). If a saved cheat validly passed but the negative probes are invalid, the code raises `InvalidInfra` and drops a valid G6 rejection. This is conservative, not a wrong verdict. Fix: add `passed == 0` to the guard.
- **N2. G11 review evidence never matches across attempts** (`factory/run.py:2296`).
  - The `g11-evidence-<time_ns>` directories accumulate.
  - The report contains a per-run `results_directory`, so the evidence digest differs on every attempt. As a result, `independent_review`'s unchanged-evidence reuse never triggers across gate attempts or resumes.
  - Fix: bind the evidence on the report with `results_directory` removed, at a stable path.
- **N3. Duplicate crash diagnostics** (`factory/gate_attempt.py:31-32`). On exhaustion, `record_crash` runs once through `on_error` and again in the `except` branch, writing two crash files for one failure.

## Verified as meeting the resolutions

- **Shared validity check:** `run_validity` is the single check used by `read_completed` (now on by default), `verdicts`, strategy, G14, calibration receipts and `verify-negative`.
- **Rows 22 and 23:** all-invalid cheats raise instead of counting as rejections (22). G10 no longer converts runtime errors into failed attempts, and `pending-<try>.json` avoids paying for the solver again (23).
- **Retry journal (B1/B2):** retries are bounded across resumes, nested exhaustion is not retried again, and budget/provider waits use no allowance.
- **Stop schema (B3):** the fields and all recovery entry points refuse exhausted cards. The legacy crash import still works.
- **G2 receipts (row 24):** contract 2 binds runner retrieval bytes to the verdict, and late_recovery plus `tools/open-g2-verdicts.py` are aligned.
- **Exact collection (row 25):** archive names and hashes match exactly, with the explicit probe and startup exceptions.
- **Pinned migration:** the policy-only migration is correctly digest-pinned.
- **Card corpus:** projecting the public card corpus changes exactly one case (`18681d`), with no card rewritten and no claim that cards authenticate hidden runs.
- **Orphan test:** the deleted `test_restore_failover_bundle.py` did load an untracked `finalize-restore.py`.
- **Row 14:** correctly left open.

## Behavior I declined to judge, and why

- **Whether 120 seconds is enough for the S11 window:** this needs a live run, which is prohibited here.
- **Whether the full suite and real-artifact runs pass:** I did not run tests, per the brief. I relied on the saved validation record.
- **Whether the 64 practice files and 58 VM cards match their stated sources:** checking would mean reading outside the repo or using SSH.
- **D-owned diagnosis and replacement after exhaustion, A routing, and E process groups:** out of scope. I only confirmed that this diff leaves those areas untouched.
- **Whether the G11 prompt wording yields good adjudications in practice:** that is a model-quality question, and static review cannot settle it.


## Elephant response

All findings accepted; none rejected. B1 restores digest-bound external attempt
workspaces and all matching calibrator transcripts, with a missing-input validator
and an early-probe regression. M1 replaces only missing tries in durable separate
series and immediately reviews a submitted replacement; a completed no-fix
replacement is never bought again. M2 excludes inaccessible unflagged searches and
uses existing bounded topup for alternatives; flagged failures remain operational.
M3 clarifies row 36's unscored D diagnosis handoff. M4 clears invalid retry counts
after success. N1 retains valid cheat counterexamples, N2 normalizes generated G11
paths, and N3 removes duplicate crash diagnostics. A self-audit additionally fixed
provider-wait review receipts so an interrupted reviewer remains available and a
partial verdict cannot be reused. The next fresh goldfish reviews these changes
and the full branch; this response does not replace that review.
