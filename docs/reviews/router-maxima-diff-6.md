# Router maxima rounding: diff review 6

**Reviewer:** fresh goldfish, read-only. Mode: REVIEW. Personas: `zoom_out` and `implementation_readiness`. Standards: `zoom-out-standard.md` and `implementation-readiness-standard.md`.
**Branch:** `t3/router-maxima-rounding`
**Base:** `49b178bfd5fd51ad7f9b22f2993db91025f6908b`
**Frozen HEAD:** `aef430984d093bb9d3ce308c515c6ff25560fdf9`
**Scope:** 17 added lines in `tests/factory/test_model_call_maxima.py`, with no production diff. The design step was skipped under ENGINEERING §1 step 2 (a fix under about 20 lines with an obvious cause). The diff is reviewed against the commit message and the user brief.

## Verdict

**PASS on the diff: no Blocker or Major findings are open.**

This verdict covers only the diff and the mutation evidence. It does **not** mean the full suite passed. ENGINEERING §1 step 4 requires the full suite to pass before merge (step 6). At review time, `/tmp/router-maxima-full-aef4309.json` reports `"status": "running"` for the frozen SHA, and the log ends partway through `tests/bench/test-launch-guards.py`. Merge stays blocked until a terminal exit-0 record exists for `aef4309`.

## What was checked

1. **The test hits the real rounding sites.** Only two places turn a Lease maximum into a reserved amount:
   - `factory/model_runtime.py:76`, `invocation_maximum`: `Decimal(str(lease.max_usd)).quantize(..., ROUND_CEILING)`
   - `factory/budget.py:147`, `reserve_invocation`: the same quantize.

   The test calls both directly. The input `0.1234567891` gives `0.123456790` under CEILING and `0.123456789` under FLOOR, so the test can tell the two apart. This closes the gap the brief describes: earlier values were already exact at nine places, so FLOOR changed nothing.

2. **Production route validation is not relaxed.**
   - The patch replaces only `router.route_maximum`, and only inside the `invocation_maximum` call.
   - `model_runtime` imports `model_router`, the same module object the test imports as `router`. So the patch reaches `valid_lease` → `valid_maximum` (`factory/model_router.py:49-52`).
   - Everything else in `valid_lease` still runs for real: the `isinstance(Lease)` check, the 32-hex `lease_id` check, the finite and future `expires_at` checks, and the membership check of route, account, billing, family and pool in `routes(model, accounts)`.
   - The type-and-value equality check in `valid_maximum` still runs. It is just compared against the synthetic tariff, which `maximum` builds from `actual`'s own `MAXIMUM_FIELDS`.
   - Production `route_maximum` and the `GATED_CLAUDE` profile are untouched. The `factory/` tree matches HEAD.

3. **The raw maximum and the rounded maximum are both reserved.** Each `subTest` uses a fresh `lease_id` and `operation_id` (uuid4) against the saved fixture `tests/fixtures/factory/stream-d/job-money.json` (committed total 200, batch deadline in 2030), read through the real `job_authority.read`.
   - The raw-float subtest (`0.1234567891`) is the one that catches the `budget.py` FLOOR mutation.
   - The Decimal subtest checks that a value already quantized stays put.
   - Both assert the persisted string `'0.123456790'`.

4. **Mutation evidence** (in `/tmp/router-maxima-rounding-mutations.json`, mirrored in `docs/reviews/router-maxima-rounding-mutations.json`):
   - **`model_runtime.py`, CEILING→FLOOR:** exit 1, failing at test line 298 with `Decimal('0.123456789') != Decimal('0.123456790')`.
   - **`budget.py`, CEILING→FLOOR:** exit 1, failing at line 307 in subtest `amount=0.1234567891` with `'0.123456789' != '0.123456790'`.
   - The two mutations ran independently. The `model_runtime` run fails at the first assertion, before any reservation, so it does not depend on `budget.py`.
   - **Restoration:** the recorded hashes `7d3580a2…` for `model_runtime.py` and `a2f9c64f…` for `budget.py` match `shasum -a 256` of the worktree files now. `git diff --quiet HEAD -- factory` is clean, so the files are restored byte for byte.
   - The baseline focused run is recorded as exit 0.

5. **Zoom-out (YAGNI, reuse, placement).**
   - The test reuses the existing `lease()` helper, the stream-d job-money fixture, `job_authority.read` and `budget.reserve_invocation`, and sits beside the other maxima tests.
   - It adds no new helpers or fixtures and no production change, and it does no redesign.
   - It targets the root gap: no earlier test used a value with a tenth decimal place.

6. **Implementation readiness.** The commit message states the input, the expected output, both paths exercised, the mutation result, and the §1 skip justification. Nothing is left for a reader to decide.

## Findings

- **Nit: the mutation scope in `budget.py` is not recorded.** `budget.py` has five `ROUND_CEILING` occurrences: the import, line 147, line 279, line 615 and line 617. The evidence says only "ROUND_CEILING -> ROUND_FLOOR" and does not say whether one occurrence or all of them were changed.
  - The failure output does show the reservation row floored, which is line 147, so the targeted path is proven either way.
  - Recording the exact line would make the evidence fully reproducible.
  - Optional.
- **Nit: an evidence file is untracked.** `docs/reviews/router-maxima-rounding-mutations.json` exists in the worktree but is not in commit `aef4309`.
  - If it is meant to be the durable record next to this review, commit it with the review file, which would move HEAD.
  - Otherwise, quote its contents in `router-maxima-diff-6.md`.
  - Optional.
- **Status, not a finding: the full suite has not finished.** It is still running (see the Verdict). Do not claim a full-suite pass or merge until `/tmp/router-maxima-full-aef4309.json` shows a terminal pass for `aef430984d093bb9d3ce308c515c6ff25560fdf9`.

## Records

- **Fixed:** none were needed.
- **Rejected:** none.
- **Murphy rows:** the change names none, and none are claimed closed. That is consistent with a test-only regression follow-up.

## Author response

PASS accepted; no blocking finding is open or rejected. Both optional nits
are addressed: the mutation JSON records the exact all-occurrence replacement,
affected source line numbers and byte-identical restoration; it will be committed
with this review and the terminal full-suite evidence. No production source
changed. The full suite remains pending on frozen aef4309 at this response.


## Terminal validation (author record)

The full suite completed at 2026-10-30T05:18:52.996164Z on the reviewed code SHA
`aef430984d093bb9d3ce308c515c6ff25560fdf9`: exit 0, 144 scripts, 0 failed.
The original review above correctly reported the then-running status. Durable
evidence: `router-maxima-full-aef4309.json` and
`router-maxima-full-aef4309.log.gz`, with SHA-256 recorded in the JSON.
Both mutation experiments failed independently and production files were restored;
`router-maxima-rounding-mutations.json` records the exact replacement scope.
No merge, push or model launch was performed.
