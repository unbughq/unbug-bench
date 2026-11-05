# durable-execution WP4 diff review 3 (verification)

Reviewer: fresh goldfish subagent (general-purpose), read-only, persona
implementation_readiness, Mode: REVIEW. Narrow verification of review 2's blocking
findings 3 and 4 and of `git diff d405fa8 630d411`. Verdict: **PASS**. Verbatim below.

---

# WP4 diff review 3 (goldfish, REVIEW mode): `de/wp4` at 630d411

**Verdict: PASS.** Findings 3 and 4 are fixed. The fix commit breaks nothing, and the test passes.

## Finding 3 (BLOCKING): Fixed
- The sentence "The engine's batch deadline then decides whether the case continues." is gone from `docs/designs/durable-execution-wp4.md`.
- The text that replaces it says `deadline_epoch` only stops new cases and extensions from starting. That matches `factory/durable/contract.py:346` ("no new case or extension starts after this") and `docs/designs/durable-execution.md:180`.
- I searched the note for "deadline". Nothing else in it says the batch deadline stops a running case. Lines 86 and 131-137 only classify `retired_batch_bound` and `provider_wait_deadline` as `infra:deadline`, which is a classification and does not contradict the contract.
- Every new citation points to the right code:
  - `budget.py:145`, `:834-839`, `:1220` and `:1247` raise `retired_batch_bound`.
  - `job_authority.py:47` and `:74` raise it too.
  - `budget.py:163-165` raises `money_wait` before any spend.
  - `budget.py:1357` stores `str(error)`, and `:885` re-wraps it.
  - `job_config.py:88`, `:96` and `:172`, and `factory_waste.py:41` and `:314`, raise `money_wait`.

## Finding 4 (BLOCKING): Fixed
I recounted from `sealed/case-*.scorecard.json` myself.
- 50 cards have `dry_run: false`, and 49 of them have `continuation_budget`. Those 49 hold 511 history stops, and 210 of them are `opencode_error` (after stripping the wrapper prefixes and taking the text before the first `:`).
- 13 cards have a `free_model_fallback` from `opencode/glm-5.3-flash-free`. They hold 89 `opencode_error` stops, out of 199 stops in all. The new wording, "89 of the 210 `opencode_error` stops", is correct. The old "89 stops in all" was wrong.
- 48 of the 49 cards give `roles.easy_calibrator.model` the value `opencode/glm-5.3-flash-free`. The one that does not is `aeefd5`, which has no `roles` at all and does not mention GLM anywhere. "48 of the 49 cards (all but `aeefd5`, which records no roles)" is correct in both places.

## Rest of `git diff d405fa8 630d411`
The diff touches five files:
- the design note;
- the stops report;
- the review file's resolution table;
- two comments in `factory/durable/classify.py`;
- `RUNNER_FILES` in `tests/factory/test_durable_classify.py`, which now also lists `job_authority.py` and `job_config.py`.

The code change in `classify.py` is comments only, so no classification changes. The new WP5a and WP1 requirements, and the edge case at `budget.py:165`, agree with the code they cite.

## Test
`tests/factory/test_durable_classify.py`, run with the given command in a detached worktree at 630d411: 20 tests, OK. I removed the worktree afterwards.

## New findings
- **NIT:** two of the edited lines run past the files' line width: line 155 of `docs/reports/durable-execution-wp4-stops.md`, and the "Runner labels" line in `docs/designs/durable-execution-wp4.md`. This is formatting only.

No new BLOCKING findings.

---

## Resolution (elephant)

Passed. The one NIT, line width, is formatting only and is left as is.
