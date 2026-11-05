# durable-execution WP4 diff review 2 (verification)

Reviewer: fresh goldfish subagent (general-purpose), read-only, persona
implementation_readiness, Mode: REVIEW. Focused verification of review 1's blocking
findings and of `git diff e511807 8854e48`. Verdict: **FAIL** (findings 3 and 4
blocking, wording only). Verbatim below; the resolution follows at the end.

---

# WP4 diff review 2: focused verification (de/wp4 @ 8854e48)

I reviewed only the fix diff, `git diff e511807 8854e48`. I checked the raise sites in `factory/` at 8854e48 myself and did not rely on the resolution table. The test command ran in a detached worktree at 8854e48, because `de/wp4` is already checked out in another worktree. Result: **20 tests, OK**. The worktree has been removed.

## Status of the review 1 blocking findings

**1. `money_wait` / `retired_batch_bound` mapped to `batch:money_bound`: VERIFIED-FIXED (mapping), with one new blocking issue in the rationale (finding 3).**
- `classify.py:102-103` now maps `retired_batch_bound` and `provider_wait_deadline` to INFRA_ERROR `infra:deadline`. `classify.py:109` maps `money_wait` to `<step>:money`, the same as `cost_limit`. `batch:money_bound` is no longer in `REASONS`. I recomputed `PUBLISHED_REASONS` at 55, matching the report's list.
- The raise sites match the note:
  - `retired_batch_bound` is a clock check in every case: `budget.py:145`, `:837`, `:1220`, `:1247` and `job_authority.py:47`, `:74`.
  - `provider_wait_deadline` is raised at `model_router.py:523`, `:593`, `:642`.
  - `money_wait` is a real committed-money overrun at `budget.py:717` and `:941`. It is a JobAuthority plumbing fault at `budget.py:141`, `:144`, `:714` and `job_authority.py:51`, `:63`, `:71`, `:73`.
- Mapping `money_wait` to `<step>:money` and letting the policy pick from the Grant label is consistent with `durable-execution.md` ("When the money runs out"; EXHAUSTED rules).
- The new tests assert both mappings for every `StepKind` and pass.

**2. Report presented co-occurrence as cause counts: VERIFIED-FIXED for the original claim, with two new unsupported numbers in the rewritten table (finding 4).**
- I recomputed from the 50 non-dry-run cards:
  - Cards with free MiniMax/DeepSeek routes: 32 cards, 466 stops, 206 `opencode_error`.
  - The other cards: 17 cards, 45 stops, 4 `opencode_error` (86b100 has 1, ce4d82 has 1, 7d8a30 has 2).
  - Stops per card: 14.56 against 2.65.
  - 13 cards have a GLM fallback, and all 13 are among the 32.
- These match the report. Rank 1 is now worded as correlation, with the confounder stated.

## New findings

**3. BLOCKING: the note's justification for `retired_batch_bound` → `infra:deadline` contradicts the contract, so a running case can be routed to DIAGNOSE because a clock passed.**
- `docs/designs/durable-execution-wp4.md:128` says "The engine's batch deadline then decides whether the case continues." But `contract.py:346` defines `deadline_epoch` as "no new case or extension starts after this", and `durable-execution.md:180` says the same. So a case already running keeps going past the deadline.
- If the runner still enforces a batch deadline under the engine, every attempt after the deadline raises `retired_batch_bound` again, in the runner's per-call timeout clipping (`budget.py:834-839`, `:1220`, `:1247`) and in `reserve_invocation` (`budget.py:145`). The policy then burns `max_infra_retries_per_step`, gives up and sends the case to DIAGNOSE. That DIAGNOSIS fails the same way and RETIREs.
- This is a wrong route under the policy: the case did nothing wrong. The note already handles the same risk for `money_wait` plumbing by putting a requirement on WP5a, but here it states a false guarantee instead.
- **Fix:** delete the sentence and add a WP5a requirement. Under the engine, the runner's call timeout comes only from `StepInput.deadline_s`, and no batch-deadline check survives in `budget.py` or `job_authority.py`. If one does survive, the policy must not count it toward `max_infra_retries_per_step`. Add the matching item to the Tests section, or hand it to WP1 as it did for the PROVIDER_LIMIT cap.

**4. BLOCKING: two claims in the rewritten "Top causes" table are not supported by the cards.**
- **Row 2, "13 cards, which hold 89 stops in all".** The 13 GLM-fallback cards hold 199 stops in all. 89 is their `opencode_error` count, which paragraph 2 states correctly as "89 of the 210". **Fix:** say "which hold 89 of the 210 `opencode_error` stops".
- **Row 2, "Every card has it, so it is not a correlate".** Card `aeefd5` has no `roles`, and no `glm-5.3-flash-free` appears anywhere in it; its events show only `opencode-go/` routes. So 48 of 49 cards have it. The same claim also appears in the existing bullet "the free GLM easy calibrator that every card has". **Fix:** say "48 of the 49 cards (all but `aeefd5`, which records no roles) have it", in both places. The conclusion that it is not a correlate still holds.

**5. NIT: the list of `money_wait` plumbing sources that WP5a must not emit is incomplete.**
- `docs/designs/durable-execution-wp4.md:110-115` leaves out these plumbing raises of `money_wait`: `job_config.py:88`, `:96`, `:172` and `factory_waste.py:41`, `:314`.
- **Fix:** list them, or state the rule without a list: WP5a must emit `money_wait` only when spend plus reservations exceeds the grant.

**6. NIT: one real money source is not cited.**
- `budget.py:165` in `reserve_invocation` raises `money_wait` before any spend, when the route maximum does not fit in what remains. The policy's WAIT_FOR_BOUND rule needs "usage reached the grant", which does not hold here, so a batch-limited grant smaller than one call's maximum gives up instead of waiting.
- **Fix:** cite `:165` beside `:717` and `:941`, and note this edge case for WP1.

**7. NIT: wrong line citation.**
- The note (`:46`) and `classify.py:138` cite `budget.py:358` as storing `str(error)`. The store is at `budget.py:1357`, and the rewrap happens at `:885` (`'Budget ledger stopped: ' + str(previous)`). Line 358 is in `settle`.
- **Fix:** cite `:1357` and `:885`.

**8. NIT: the label sweep misses `job_authority.py`.**
- `RUNNER_FILES` in `tests/factory/test_durable_classify.py` leaves out `job_authority.py`, even though it is a cited source of both reviewed labels. A new label added there would not fail the test.
- **Fix:** add `job_authority.py` to `RUNNER_FILES`. Add `job_config.py` too if its `money_wait` is in scope.

The rest of the fix diff is correct:
- **Wrapper loop:** the bounded loop strips the wrappers correctly, and 9 wrappers fall through to `infra:unclassified_stop`, which is still INFRA_ERROR.
- **Label sweep:** the IfExp and f-string handling in the sweep is correct.
- **CLI-version pattern:** the broadened `_CLI_VERSION` pattern only ever sees the head before the first `:`.
- **Case content:** no case content can reach a reason; every reason still comes from the fixed tables.

## Verdict: FAIL

Findings 1 and 2 from review 1 are fixed. Findings 3 and 4 are new blocking issues. Finding 3 is a design-note claim that contradicts `contract.py:346` and leaves a wrong DIAGNOSE route open. Finding 4 is two report numbers the cards do not support. Both need wording fixes only: one requirement added to the design note, and two phrases corrected in the report.

---

## Resolution (elephant)

Fixes made by the WP4 writer on `de/wp4`, at the elephant's direction. Test file
afterwards: 20 tests, OK.

| # | Severity | Resolution |
|---:|---|---|
| 3 | BLOCKING | **Fixed.** Deleted the sentence "The engine's batch deadline then decides whether the case continues." In its place the design note states that `deadline_epoch` only stops new cases and extensions (`contract.py:346`, `durable-execution.md:180`). It adds a requirement on WP5a: under the engine, the runner's call timeout comes only from `StepInput.deadline_s`, and no batch-deadline check survives (`budget.py:145`, `:834-839`, `:1220`, `:1247`; `job_authority.py:47`, `:74`). It adds a requirement on WP1: if such a check does survive, its `infra:deadline` must not count toward `max_infra_retries_per_step`. The elephant is also passing both requirements to WP5a and WP1 directly. |
| 4 | BLOCKING | **Fixed.** Row 2 now says "13 cards, which hold 89 of the 210 `opencode_error` stops". Both places that said every card has the free GLM route now say "48 of the 49 cards (all but `aeefd5`, which records no roles)". I recounted this: 48. |
| 5 | NIT | **Fixed.** The note states the general rule: WP5a emits `money_wait` only when spend plus reservations exceeds the attempt's grant, and every other source must raise a plumbing label. It also lists today's plumbing sources, including `job_config.py:88`, `:96`, `:172` and `factory_waste.py:41`, `:314`. |
| 6 | NIT | **Fixed.** `budget.py:163-165` is cited beside `:717` and `:941`, in the note and in the `classify.py` comment. The reserve-before-spend edge case is written up for WP1: usage stays below the grant, so WAIT_FOR_BOUND does not fire. The note gives two options: treat that EXHAUSTED as a money wait, or set the minimum grant to at least one call's maximum. |
| 7 | NIT | **Fixed.** The citation is now `budget.py:1357` (the stored stop) and `:885` (the re-wrap), in the note and in `classify.py`. |
| 8 | NIT | **Fixed.** `RUNNER_FILES` now includes `job_authority.py` and `job_config.py`. They raise only `money_wait` and `retired_batch_bound`, which are already in the reviewed mapped set, so the unclassified set is unchanged. |
