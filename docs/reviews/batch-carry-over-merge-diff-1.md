# Goldfish review: batch-carry-over merge resolution (diff 1)

**Mode:** REVIEW (zoom_out + implementation_readiness, merge resolution only)
**Target:** `41375f1` (parents `9ddb70e` carry-over, `6ffec7c` stream B2). Suite record is in `3060382`; HEAD is `3060382150fb503b88f123ef5ad2804bfb90a595`.
**Basis:** This is a small conflict relocation, so no design step. Reviewed against the merge commit message, the parent's stated requirements and the existing batch-carry-over design.

## Verdict: PASS

There are no Blocker or Major findings.

## What I checked

1. **`transfer.prepare` stays in reserve, before the target lock.** `factory/batch_holder.py:241-243`: `reserve` calls `enabled()`, then `prepare(policy, root, home)`, then `money.manifest`, then `money.locked`. It runs on every reserve request, before the lock, as in `9ddb70e`. `_admit` does not call it, which is correct: the dry qualification must not run transfer preparation.

2. **Job resolution, template-only refusal and lineage are in `_admit`.** `factory/batch_holder.py:203-207`.
   - `service.resolve_job` replaces B2's `name not in record['jobs']` check. Derived `-rN` names now resolve, as carry-over intended. Unknown names still raise `ValueError`.
   - The template-only refusal runs first, before any read or mutation of state.
   - `service._lineage(service._load(...))` moved out of `reserve` into `_admit`. `reserve` no longer calls it, so it runs once, not twice.
   - `tools/qualify-batch-inputs.py:35` calls `holder._admit`, so the qualify tool now gets the template-only refusal and the lineage check.
   - When the batch directory is absent, `_load` returns an empty journal (`factory/batch_service.py:94-97`), so `batch_absent` qualification still works.
   - The lineage check now runs after `load_locked` instead of before it. Both calls are read-only, so the order has no effect.
   - The replay path (`identity in ops`) still runs after the lineage check, the same order as carry-over.

3. **The imported-base guard is in `_admit`.** `factory/batch_holder.py:231-235`. The branch order is: advance, then imported-base (authority equality and `len(sources) == 1`), then `sources[-2]`. This matches `9ddb70e` exactly. An imported base never reaches `sources[-2]`. The guard was removed from `reserve`, so it is not duplicated.

4. **`empty_input` uses the resolved case.** `factory/batch_holder.py:237`: `empty_input(root, directory, resolved['case'])`. B2 used `record['jobs'][name]['case']`, which would raise `KeyError` on derived names and give the wrong case for imported carried jobs. The merge fixes this.

5. **`reserve` is thin.** It calls `prepare`, then `manifest`, `lock`, `_operations`, `load_locked`, `_admit`, then the replay repair or the persist-and-journal step. The admission logic in `reserve` that carry-over had added is gone. Nothing from either parent was dropped (I compared both parents' bodies line by line).

6. **Both stream-D sections are preserved.** `docs/designs/stream-d.md:3714` has "Cross-batch implementation addendum reference" and `:3728` has "Item 7 remaining-increment checklist". `git diff <parent> 41375f1` shows zero removed lines against either parent. No conflict markers are left anywhere in the tree (`git grep` at `41375f1`).

7. **The new test calls `_admit` directly.** `tests/factory/test_batch_transfer.py:333-341`. Under `money.locked`, it calls `holder._admit(..., 'j', None)` on a template-only imported root. It asserts the `template-only` refusal and that the in-memory money state equals a deepcopy taken before the call. It sits inside `test_child_only_import_cannot_launch_its_template_root`, next to the existing reserve-path assertion that carried debit stays at `1000.000000000`. The two-hop and queued-child tests still exist and run.

8. **The suite record matches the log and the code.**
   - The `.json` has `code_commit` `41375f139d6e…`, `status` passed and `exit_code` 0.
   - The `.log` SHA-256 is `d6f77139…d6a30a`, which matches `log_sha256`.
   - The log has 166 `== script ==` sections and ends with "166 test scripts run; 0 failed." It contains no `FAILED` or `Traceback` lines.
   - The log includes `test_batch_holder`, `test_batch_transfer` (14 tests), `test_carry_over*`, `test_transfer` and `test_qualify_batch_inputs` (11 tests).
   - `git diff 41375f1 3060382 -- . ':!docs/reports'` is empty, so the code in the record is exactly the merged code.

## Findings

- **Nit:** `tests/factory/test_batch_transfer.py:333-341`. The test checks only the in-memory `state`. It does not check that `money.json` or the journal on disk are unchanged, and it does not call `qualify()` itself. This is acceptable: `_admit` is documented as in-memory only, and the tool calls `_admit` directly. If you want a stronger check, add one assertion that `qualify(...)` returns `admission='refused'` for `'j'`.
- **Nit:** `docs/designs/stream-d.md:3725-3727`. There are two blank lines between the addendum and the item 7 checklist. This is cosmetic only.
- **Nit (records):** The `41375f1` merge commit has no `Reviewed-by:` trailers. It is a merge of upstream into the feature branch, not the `factory-simplify` merge. Make sure the later merge into `factory-simplify` lists `docs/reviews/batch-carry-over-merge-diff-1.md`, together with the earlier carry-over reviews.

## Out of scope

- The inherited carry-over feature: transfer, imported roots, two-hop lineage and queued-child semantics. The fresh diff review at `9ddb70e` already passed it.
- The upstream changes in `6ffec7c` (B2 inputs and empty-launch qualification) and `2a36f04` / `8d063cf`, beyond the conflicting hunks.
- The earlier deferred non-blocking follow-ups for the feature.
- Murphy row closures. The merge claims none.
- Whether `empty_input` semantics are correct for imported cases whose evidence lives in the source batch. That behaviour is inherited.
- The qualify tool not catching `MoneyWait`, which predates this merge.

I made no writes, ran no workers, made no paid or model calls, and did no pushes or merges.

## Implementation disposition

Accepted PASS. No Blocker or Major findings; no code changes after review.
The optional stronger qualification assertion and cosmetic spacing are deferred.
The eventual factory-simplify merge must include this review and the earlier
carry-over reviews in Reviewed-by trailers. That merge is not performed here.
No Murphy row closes. No push or worker launch was performed.
