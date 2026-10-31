I have all the information I need. The design is a small, well-scoped increment on an already-implemented item-4 foundation. Let me now write the final review report against the three personas and the two standards.

I have verified all the factual claims of the design against the code. Here is my complete review report.

---

# Goldfish Review — `docs/designs/stream-d-row13.md`

**Mode:** REVIEW (design review)
**Personas:** zoom_out, design_critic, implementation_readiness
**Standards:** heilmeier-standard.md, implementation-readiness-standard.md
**Worktree:** `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`
**Target:** `docs/designs/stream-d-row13.md` vs `factory/stress_progress.py`, `factory/run.py`, `factory/ordinary_retry.py`, `factory/model_runtime.py`, `docs/murphy-register.md` row 13, and `tests/factory/test_stream_d_retries.py`.

## Verdict: **PASS** (no blockers)

**Blockers:** none.
**Nits:** 2 (non-blocking).

---

## 1. Does the design state the real problem? (zoom_out + heilmeier)

The design's root problem is **confirmed against the code**, not assumed:

- `stress_progress.run()` (lines 87–146) calls `aggregate()` only after a category row completes or raises `stress_validation_exhausted` at the top of the `while` loop. When `answer()` raises a `BudgetError('timeout')` (see `ordinary_retry.py:114` → `model_runtime._call` lines 409–410 `raise BudgetError('timeout')`), the exception unwinds out of `answer`, out of the `for category` loop, out of `stress_progress.run`, and out through `run.write_and_attack` at line 1509 (`stress_categories(...)`). The `finally` at `stress_progress.py:119–124` preserves partial bytes, but **`aggregate()` never runs**, so `attacks/round-N.json` is left at whatever `review_admitted()` wrote (`{'complete': False, 'blocking': ['review incomplete']}` at `run.py:1496`) or is absent entirely.
- The aggregate shape produced by `aggregate()` (lines 67–83) is `{complete, blocking, unfinished_validation, non_blocking, freshness_review, cheats_tried}`. It contains **no** `status`, no per-category coverage inventory, no `operation_id`/`round` echo, and no index of the `*-partial-*.json` files that `invoke`'s `finally` retained. So the framing "an unexplained empty aggregate with no explicit pending status, coverage inventory or interrupted-output index" is precisely correct.

The design names the fix as *minimum*: add status/round/operation/category_state/coverage/inventory to the aggregate, write it **before** publication/dispatch, and re-generate on `BudgetError` after the `finally` that saves partial bytes. This directly targets the report-loss half of row 13 and nothing else. YAGNI is honored: it explicitly refuses item-7 routing, automatic diagnosis, fresh model calls, money changes, and legacy non-batch stress.

## 2. Scope honesty and Murphy-row discipline (design_critic + ENGINEERING §2)

- **Correct non-claim.** The design is explicit that it closes *only* the report-loss half of row 13, and that automatic diagnostic recovery stays open under row 9 / item 8 (`stream-d-row13.md:36–39`). This is a faithful continuation of the already-narrowed wording in `stream-d.md:2488–2493` ("NOT fully closed by item 4 alone"). No over-claim of closure is present.
- **Correct deletion discipline.** "Delete no execution path or allowance" (line 22) is satisfied. The one cleanup listed — removing the now-redundant `write_and_attack` barrier install once test contexts use `Ctx`, plus the `http_5xx` prose fix — is cosmetic and optional, correctly flagged as such.
- **Correct routing posture.** "No item-7 routing changes" matches the register line 13 "Fix" column (commit findings/coverage incrementally; continue only unfinished coverage) and matches the parent ruling that item 7/8 stays separate (`stream-d.md:2762`).

One residual honesty point (nit-level, not a defect): the design says the aggregate gets `operation_id` and `round`. The code already carries `operation_id` and `round` on the **receipt** (`attack-state.json`) via `stress_progress.run` line 57/60, not on the aggregate. Echoing them into the aggregate is *new surface*, and the design should state whether these are authoritative dupes of the receipt or independent facts — a reviewer reading only the aggregate must not be able to get a different `operation_id` than the receipt. Minor.

## 3. Pending ≠ pass semantics (design_critic — correctness)

The central correctness guarantee is sound and already half-true in code:

- "complete stays false until all coverage completes" is enforced today by `aggregate()` line 68 (`all(...)` over `CATEGORIES`), and by `finish()` raising `stress_validation_exhausted` when a no-progress category is incomplete.
- "uncompleted CLI output is evidence only, never promoted to findings or coverage": `aggregate()` reads only `row['results']` (hash-bound completed filings), never the `*-partial-*.json` files. The design's promise to add an *index* of those partials without promoting them is consistent.
- "Previously authenticated findings survive": the retain-and-reaggregate loop (lines 70–83) already unions prior categories. The design's re-generate-after-`finally` step preserves this.

The one thing to verify at implementation: the `BudgetError` path must re-run `aggregate()` *after* the `finally` in `stress_progress.run`, but that `finally` is inside the `invoke` closure (lines 111–124), while `answer()` raises from `ordinary_retry.answer`. The design says "regenerate the report after the existing finally block saves partial bytes" — the implementer must place the regeneration in a `try/except` around the whole category loop, not inside `invoke`. The design says the right thing at the level of intent, but not the exact location (see readiness nit below).

## 4. Durability and honest report-loss closure (implementation_readiness)

The test plan is the strong point. It names:

- real saved practice case + 5813be ledger through `write_and_attack` and actual `ModelRuntime` (matching ENGINEERING §2 "real artifacts", and the established harness in `test_stream_d_retries.py`).
- three timeout cases: first-category with **no bytes**, malformed partial bytes, and timeout after two completed categories — the no-bytes case is precisely the gap the existing `test_category_kill_resumes_only_unfinished_and_preserves_operation` (which writes a `category_complete: false` file before kill) does **not** cover.
- assertions: valid pending report, exact retained coverage, partial digest, pending receipt, **unchanged round/operation**, and **no fabricated findings/pass**.
- archive→restore→rebuild production Ctx→resume-only-unfinished→`report becomes scored` with unchanged completed bytes and operation.

This is genuine saved-artifact control-flow proof and it correctly declines to claim a live model-timeout. It satisfies the "row closes only via a real-artifact test" rule.

The register update requirement (ENGINEERING §2: elephant sets `Status: closed` + `Closed by` test path in the same commit) is implicitly satisfied, but the design should name the *exact test path(s)* that will go in `Closed by`. That is a nit, not a blocker.

## 5. Zero-decision rule vs. what's left unsaid (readiness — nits)

Two implementation decisions are left slightly open, both minor, neither rising to "design choice":

- **Nit A — regeneration location.** "regenerate the report after the existing finally block" does not spell out the enclosing `try/except` at the `for category` loop level in `stress_progress.run`. A fresh implementer could misread it as adding the regeneration inside `invoke`'s `finally`, which would run per-file, not per-operation. One sentence positioning it would close this.
- **Nit B — aggregate schema.** "Extend the aggregate with status, round, operation_id, category_state, coverage for every category/subcheck, and an index of retained partials" is complete in *shape* but not in *placement*. `aggregate()` currently writes through `atomic_json(report, result)` and is also read by `attack_report`/`classify` via `run.py:1516`. Adding fields must not break `classify` (which validates `complete`/`blocking` and may reject unknown keys — see `attack_findings.classify`). The design does not note that the new fields must be additive and tolerated by `classify`, or that `attack_report` must be updated to preserve them. This is the single highest-skill implementer risk and deserves one line.

Neither nit is a YAGNI, correctness, or standard-compliance failure; both are minor clarity gaps.

---

## Summary

| Persona | Finding |
|---|---|
| zoom_out | Root problem verified in code; minimal, non-speculative scope; correct reuse of item-4 machinery. PASS. |
| design_critic | No over-claim of row 13; routing/deletion discipline correct; pending≠pass semantics sound and consistent with existing `aggregate()`. PASS. |
| implementation_readiness | Test plan is real-artifact, names the no-bytes gap, and asserts no fabricated pass. Two one-line clarity gaps (regeneration location; aggregate-vs-`classify` compatibility). PASS with 2 nits. |

**PASS.** Fix the two nits optionally before implementation; neither blocks.

---

Skipped / not checked: I did not run the suite, did not open the practice-case/5813be fixtures to confirm the exact test file name they'd land in, and did not read `attack_findings.classify` to verify it tolerates additive aggregate fields (that is nit B, for the implementer to confirm). Risk: the "leader must update `docs/murphy-register.md` row 13 `Status` + `Closed by` in the same commit as the test" rule is implied, not stated — the elephant must remember to do it.

## Elephant response

Accepted. Catch surrounds answer(), outside invoke's finally; additive metadata survives classify and attack_report; identity echoes the pending receipt. The old aggregate already existed before calls, but lacked explanatory metadata (review's absent-aggregate wording is inaccurate). Claude failed ENOTFOUND; requested DeepSeek fallback passed. No blockers.

