# Goldfish diff review 3: practice4-checkpoint-carry (nit follow-up)

- **Reviewer personas:** Skeptical Architect (zoom_out) and Implementation Readiness Goldfish (`tools/egm/agents/zoom_out.md`, `tools/egm/agents/implementation_readiness.md`)
- **Standards:** `implementation-readiness-standard.md`, plus the zoom-out audit vectors
- **Mode:** REVIEW
- **Target:** `229ba00..9d4202918c654e1fda03ab0f5c1ae7ae4f49b9a1`, a single commit `9d42029` ("Resolve practice4 diff review 2 nits") on `origin/claude/practice4-release-prep`. I fetched before reviewing.
- **Context read at head:** `docs/designs/practice4-checkpoint-carry.md`, and `docs/reviews/practice4-checkpoint-carry-diff-2.md` with its Elephant response.
- **Method:** read-only. I used `git show`, `git diff` and `git grep`. I hashed the fixtures from `git show` bytes. I did not run the test suite, so the focused-test counts in the Elephant response are taken as stated.

## Verdict: PASS WITH NITS

All five diff-2 nits are handled as described. The datetime Clock patch is correct, it fixes the 2026-11-06 time bomb, and it does not mask any admission logic. The commit touches no production code, fixture byte or EXPECTED literal. The Murphy edit closes nothing. I found two small wording nits and no blocking problem.

### Checks that passed

- **Scope of the change is tests and docs only.**
  - `git diff --stat 229ba00 9d42029 -- factory/ control/ tests/factory/fixtures/` is empty.
  - The 7 files changed are 5 docs and 2 tests.
  - Fixture directory: the 16 tracked files are unchanged. All 15 sha256 values listed in `provenance.json` match the head bytes (I checked 15, with 0 mismatches).
  - No EXPECTED literal or batch manifest was touched.
- **Nit #3 (Clock patch) is correct.**
  - `tests/factory/test_boat_retirement.py:37-40` defines `Clock(datetime)` with `now` fixed at 2026-11-03T12:00Z.
  - `:51-52` patches `datetime` in `holder`, `practice` and `job_authority`, and registers `addCleanup` for each.
  - This is identical to `tests/factory/test_startup_smoke.py:47-50,83-84`.
  - All three modules use `from datetime import datetime, timezone` (`batch_holder.py:4`, `practice.py:3`, `job_authority.py:8`), so replacing the name with a subclass is valid.
  - The other uses of `datetime` keep working on the subclass: `fromisoformat` at `batch_holder.py:491` and `job_authority.py:44`, and `.isoformat()` at `:384`.
- **The patch does not mask real admission logic.**
  - The patch replaces only the "now" input.
  - `reserve` (`batch_holder.py:365-375`) still runs the real `enabled`, `prepare` (which returns early for -3, `batch_transfer.py`), `_operations`, `load_locked` and `_admit`.
  - `_admit` still runs the real `practice.matches`/`practice.admission` (`:266-268`), the deadline check (`:293`), the money/incident checks and `authorize_locked`. Only the clock value changes.
  - `job_authority` is not reached in-process on this path, because no `job_authority` import exists in `batch_holder`, `batch_money`, `batch_service`, `practice` or `boat_lifecycle`. That patch is a harmless no-op, kept for parity with the existing pattern.
- **The negative control claim is consistent with the code.**
  - With `now` at 2026-11-08, the first time-dependent check reached is `practice.admission` (`practice.py:258-262`), called from `batch_holder.py:268`.
  - That check comes before the `retired_batch_bound` check at `:293`.
  - `deadline - now` is negative, which is ≤ `TIMING['ttl_seconds']` (3600), so it raises `MoneyWait('cleanup window unavailable')`. This is exactly the message the Elephant reports.
  - No earlier step (`enabled`/`practice.active`, `prepare`, `_operations`, `load_locked`) reads the clock. So the patched clock really is the gate, and the control discriminates.
- **No remaining real-clock dependence on the batch deadline.**
  - Subprocess paths run unpatched code: `bin/boat-call`, `bin/boat-spend --settle`, the `boat-launch-guards.sh` guard and `boat_lifecycle.py delete`. Through `boat_lifecycle.bounded_context` (`:285-335`) they reach only `holder.active`, `practice.matches`, `_operations`, `_config` and `practice.deadlines(started)`. None of these compares now against `batch_deadline`.
  - `boat-spend` uses `datetime`/`time` only for stamps and monotonic timeouts.
  - The remaining `time.time()` uses in the test (`:100-102` and the per-test `started` values) are relative.
  - The Elephant's statement about `boat_lifecycle` holds.
  - Mixing the fixed in-process clock with the real `time.time()` is safe: `pending_since` is only parsed (`batch_holder.py:81`) and never compared with the worker `started` time.
- **Nit #1 is fixed.**
  - The test is renamed to `test_whole_batch_refuses_without_current_opt_in` (`tests/factory/test_practice4_carry.py:134`), with a batch-wide comment at `:135-136`.
  - The design (`practice4-checkpoint-carry.md:64-66`) and the runbook (`practice-run.md:76-77`) state that dormancy is procedural only once -4 is opted in.
  - The old name survives only in historical review records (diff-1 `:122`, diff-2 `:50`), which is appropriate.
- **Nit #2 is fixed in the design, which was the reviewer's allowed alternative.**
  - The design `:68-75` names the three projections.
  - The listed keys match the fixtures exactly: `source-public` = {manifest_json, public_policy, snapshot}; `collection-public` = {generation_manifest, journal}; `publication-public` = {current, outbox}.
  - The design gives the Murphy-recorded evidence path and states that the journal parts are bound by no pin.
  - The wrong reason in the diff-1 response 3 is corrected in place with a dated note (`diff-1.md:131`).
- **Nit #4 is fixed, and the Murphy edit closes nothing.**
  - `docs/murphy-register.md:89` (`new-smoke-1`) now reads "…run before practice; lifecycle proof failed (`new-boat-stop-capture-1`); its prepared continuation…".
  - Status stays `open`, `Closed by` is unchanged, no row was added and no other row changed. This is allowed by ENGINEERING.md §2 (`:93-97`).
- **Nit #2 from diff-2 (factory/practice.py left untouched) is honored.** `factory/` is unchanged.

## Findings

### 1. NIT: the Elephant response overstates the hash coverage of `provenance.json`
- **Evidence:** `docs/reviews/practice4-checkpoint-carry-diff-2.md:91` says "all 16 files in the fixture directory keep their recorded hashes, including the 15 listed in `provenance.json`". As diff-2 finding 2 established, `provenance.json` has no recorded hash anywhere. Only 15 hashes exist. The 16th file is unchanged, but it is not hash-pinned.
- **Fix:** change the sentence to "`provenance.json` is left byte-identical; the 15 hashes it lists are unchanged (it pins no hash of itself)."

### 2. NIT: the renamed test claims the whole batch but tests only the `practice` job
- **Evidence:** `tests/factory/test_practice4_carry.py:134-144` is named `test_whole_batch_refuses_without_current_opt_in`, but it calls `holder.reserve(..., 'practice', None)` only. The claim holds by construction, because `enabled()` at `batch_holder.py:48-55` ignores the job name. But the test name now asserts more than the test exercises.
- **Fix (optional):** loop the reserve over `('smoke', 'practice')` inside the existing subTest, or soften the name to `test_batch_opt_in_gate_refuses_practice_without_current_opt_in`. No production change is needed.

No other new problems were introduced. The design's remaining process step, one final full offline suite on the exact landing tree, is still outstanding. The Elephant says its result will be recorded in PR #1.

---

## Record (parent session)

- No blocking finding is open. Under ENGINEERING.md section 1, the diff review passes.
- Nits 1 and 2 are optional and were **not applied**, so the tested head `9d42029` stays the tree the full suite ran on. They can be picked up in any later touch of these files.
- This file is the only change after `9d42029`. It is documentation only and does not change the tested code.
