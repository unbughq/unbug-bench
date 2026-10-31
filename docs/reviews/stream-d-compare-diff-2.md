**Goldfish diff re-review: stream D item 6, isolated extension comparison (`c32e884..HEAD`, branch `t3/stream-d-gates`, HEAD `34bcedf`)**

Mode: REVIEW. Personas: zoom_out and implementation_readiness. Standard: implementation-readiness-standard.md. I reviewed the diff against the item 6 section at the end of `docs/designs/stream-d.md`, including the final "Diff-review-1 resolution". I also checked it against `docs/reviews/stream-d-compare-diff-1.md`. I wrote no files. I did not rerun the full suite. I reran only `tests/factory/test_extension_compare.py`: 16 tests, OK.

**Verdict: PASS.** No blocking findings remain open.

### Prior blocker 1 (plumbing changes reroll a scored pair; compare and propose disagree): fixed

- **Binding.** `_binding` (`extension_compare.py:53-56`) is now `digest({stage, scientific_version, case_sha256})` for every stage, as the resolution says.
  - `scientific_version` already drops `case`, `seed`, `slot`, `version`, `UNBUG_FACTORY_SLOT`, `bench_workers` and `concurrent_roles` (`gate_state.py:192-212`).
  - So none of those settings can invalidate a receipt any more.
- **What the receipt still pins.** Schema 2 adds `execution` provenance (`:70-73`). It is checked for its key set only, not its values. It sits inside the receipt bytes, so its hash is still bound.
- **G16 calibration identity.** `_calibration` drops only the top-level `seed` and `slot`.
  - I checked `judge_dependencies(calibration=True)`: it carries no settings and no seed, so no hidden seed or worker field is left.
  - Every other field of `calibration_identity` maps to a stage in the version vector. Its files, limits, model, effort, runs and prompt are covered by G16 or G8 (`*.md`, `harbor/**`, STRATEGY) or by stress (`attack_findings`).
  - So a change to the calibration identity while the version vector stays equal is not reachable in practice.
- **Shared selector.** `extensions.comparison_pair` is now used by both `compare` (`:272`) and `propose`.
  - It follows the stated order: matching retained reconstructions win over the original, then the first scored pair, then the latest pending one.
  - The duplicate filter in `propose` is gone. A `None` outcome now returns pending instead of crashing on a subscript.
- **No reroll of a retained score.** If a retained scored reconstruction cannot be verified, `compare` returns `pending` (`:285-288`). It does not evaluate again or append a rival score.
- **Regression test.** `test_execution_plumbing_cannot_reroll_scored_pair_or_disagree_with_admission`:
  - It starts pooled (4 workers) and drops to 2, then flips `concurrent_roles`, changes the slot and slot environment, and adds 5 to the seed.
  - It asserts the version vector is unchanged and makes zero evaluator calls (the evaluator is patched to raise).
  - It asserts the result is still `progress`, `propose` returns an identical proposal, `verify_proposal` passes, and the history bytes are unchanged.
  - The fixture's evaluator makes G16 fail, so the scored receipts it reloads include both a stress receipt and a G16 receipt with calibration identity, under the moved seed and slot.
  - `test_..._g16` checks separately that `_load` succeeds with a moved seed, slot, workers and environment, and still refuses a changed calibration binding.
- **Serial versus pool.** The test stays pooled throughout. Going from serial to pool adds `bin/factory_pool.py` to the inventory and changes the version. The resolution documents this as legitimate.

### Prior nits: all addressed

1. **Adapter programming errors.** Errors raised inside `evaluate` now propagate. Only `InvalidInfra`, stress `freshness_unresolved` and malformed returned results become pending (`:193-215`). `test_adapter_programming_errors_propagate_without_scoring` covers `ValueError`, `TypeError` and `FileNotFoundError`, with history bytes unchanged.
2. **Duplicate filter in `propose`.** Removed through `comparison_pair`.
3. **Compare-before-propose.** The `propose` docstring now states the requirement.
4. **Support-copy test.** It now asserts a G5 receipt and its `comparison-support/G5/same.json` content, as well as stress.

### Other checks

- **Scope.** There is no default `run.gN` adapter and no diagnosis enablement. Nothing is wired for production evaluation, processes, money or continuation; that is item 7.
- **Merge.** Merging `c32e884` brought no item-6 code conflicts. `git diff c32e884..HEAD -- docs/murphy-register.md` is empty. The inherited register rows belong to their original streams.
- **Suite record.**
  - Run 3 tested `eff8114`: 157 scripts, 0 failed. The committed `-3.log.gz` decompresses to SHA-256 `57116de0…c404`, which matches the report. Its tail reads "157 test scripts run; 0 failed".
  - The log shows the comparison tests at 16 passed.
  - `34bcedf` changes only the report and the log after that run.
- **Murphy rows.** None close, which is correct. "Supports row 9; row 39 stays open until there is a capped-submission artifact" matches the design and the report.

### Nits (non-blocking)

1. **Stale design text.** In "Exact contracts and design-review-1 resolutions", these lines still state the old contract:
   - `schema_version (1)` and the field list without `execution`;
   - "Require exact fingerprint";
   - the stress binding formula that includes `seed` and `slot`.

   The same old wording appears in "Isolated execution and receipts" ("Gate binding is item 5's `gate_state.fingerprint`; stress binds case/seed/slot") and in design-review-2.

   The final resolution supersedes all of these, but only implicitly. Add one sentence to it, or strike the lines, so that the item 7 implementer is not misled.
2. **An unverifiable retained score stays pending with no recovery path.** The resolution says it "needs recovery", but no recovery is defined. In practice it is unreachable: the binding and calibration identity follow the version vector, and tampered bytes raise `BudgetError` in `_save_evidence`. Item 7 should still treat this pending state as bounded, retiring the case or counting it as infra waste, rather than retrying it forever.
3. **Two preference orders.** `_entry_evidence_root` prefers the newest matching comparison, while `comparison_pair` prefers the first scored one. Both match on equal snapshot evidence digests, so the bytes are identical and the result is the same. The different orders read inconsistently, though, and a one-line comment would help.

## Elephant response

PASS accepted; no blockers remain. Nits 1–3 accepted. The final design resolution now explicitly supersedes the earlier schema-1 field list, full-fingerprint rule and stress seed/slot formula. It states that item 7 must bound an unverifiable retained score under the existing batch authority, without rerolling or retrying indefinitely. A comment explains that evidence-root lookup chooses only byte-identical copies of the already-selected outcome, so reverse location order cannot change the verdict. These are documentation/comment-only changes; production behavior is unchanged from the reviewed full-suite revision.

