**Verdict: FAIL.** Three blocking findings are still open. All five blockers from design review 1 are resolved as written, but the new contracts leave three holes that either make comparisons hang forever or let a result be scored wrongly.

Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: heilmeier-standard.md, implementation-readiness-standard.md. Scope: the item 6 section of `docs/designs/stream-d.md` (lines 2356–2560), including "Exact contracts and design-review-1 resolutions". I checked it against `factory/extensions.py`, `factory/gate_state.py`, `factory/run.py`, `factory/gate_pipeline.py` and `factory/prompts/attacker.md`. No files were written.

### Prior blockers 1–5: all resolved
1. **Admission from a comparison outcome:** resolved. Both `verify_proposal` and `_save_case(entry)` now use an internal resolver, root-relative symlink checks are specified, and the test path compare → propose → verify → admit is required.
2. **Workspace and receipt contracts:** resolved. `Workspace` has the fields that `gate_state.inputs`, `scientific_version` and `run.calibration_identity` read. The bench is the read-only source bench, and the configuration is copied once at entry. The receipt's path, fields and support namespace are exact.
3. **Pending versus fail:** resolved in principle. An inconclusive result is a fail, consistent with item 5. Retry ownership is given to item 4 (inside evaluators) and item 7 (admission and bounds). Blocker 2 below covers a gap in the list itself.
4. **G2 and freshness:** resolved for G2 (read-only retrieval, mutation refused, both paths tested). The same flaw remains in stress; see blocker 1.
5. **Reuse policy:** resolved. Reuse is exactly `REUSABLE`, pass receipts only, from an explicit source order. G8/G9 need an exact match, and G16 checks `calibration_binding` with an explicit bench.

### New blocking findings

**1. Stress always changes the case, so every comparison stays pending.**
- Severity: Blocker. Scope: "Isolated execution and receipts" ("a gate that changes case bytes is rejected as pending"), the G2 paragraph, and the stress row of the mandatory-fresh list.
- Stress is the first stage and always runs fresh. `factory/prompts/attacker.md:57` tells the attacker to append its searches to `<case_dir>/freshness.jsonl`. The `run.case_hash` docstring (`run.py:806`) says it ignores that file because "the stress tester appends to it".
- `extensions.tree` and the design's case digest include `freshness.jsonl`. So a normal stress run changes the case and the comparison returns pending. This repeats every retry, before any gate runs.
- The stress loop's freshness review also raises `BudgetError('freshness_unresolved')` when a request is malformed or the pinned version is unknown (`run.py:986-993`). These failures are deterministic for a case. Under the design, `BudgetError` propagates, so the result is an endless hold rather than pending or fail.
- G2 also needs `counted["attacker"] >= 2` (`run.py:1998`), and those attacker rows come from stress. The design must decide how stress works inside a comparison:
  - where the attacker's searches go (work evidence, not the case);
  - whether G2 counts saved attacker rows or the fresh stress rows;
  - how `freshness_unresolved` is classified.
- It must then test the stress mutation and refusal paths the same way it tests G2.

**2. The pending list misses the codebase's existing invalid-execution signals.**
- Severity: Blocker. Scope: the "Pending classification is:" paragraph and the G2 paragraph.
- **Missing invalid-infra marker.** The existing in-band marker is `info['classification'] == 'invalid-infra'`. `GatePipeline.check` turns it into `InvalidInfra` (`gate_pipeline.py:57-59`). G2 sets it whenever it fails without a confirmed hit (`run.py:2008-2009`), which covers malformed evidence, unresolved review and too few searches. The design's "exact" list has no such key. An adapter that reuses G2's logic would therefore score invalid evidence as a scientific fail. That produces a false regression and retires the case, which is exactly what item 6 says it prevents.
- **Contradiction with G2.** The design's sentence "Insufficient history is a valid scientific fail" contradicts how G2 classifies the same outcome today. One rule must win, and the classifier must state it.
- **`CaseProblem`.** `GatePipeline.check` turns `CaseProblem` into a scientific fail (`{'problems': [...]}`, `gate_pipeline.py:54-55`). Under the design, "other exceptions propagate without publishing", so a contract-violating outcome blocks the comparison forever.
- **Fix:** derive the classifier from `GatePipeline.check`'s existing semantics instead of a new list: `classification: invalid-infra` → pending, `CaseProblem` → fail. Add tests for both.

**3. A comparison can be re-run until it gives a different answer.**
- Severity: Blocker. Scope: "A pending pair is retained…", "Retrying a completed pair may rerun mandatory-fresh stages; identical pair bytes deduplicate", and `extensions.propose:254-258`.
- `compare` always executes. Its fresh stages (stress, G7, G10, G11, G17 and model-backed G2) are random, so a rerun gives different bytes and never deduplicates. Each rerun is appended to the history.
- `propose` uses the newest pair whose versions match. So a rerun can replace a scored progress with pending or regression, or a regression with progress. The caller can effectively re-roll a scientific verdict. Nothing says that `compare` is skipped when the original entry/outcome pair already matches the current version vector.
- **Fix:** state that `compare` first looks for a retained or original pair that is not pending and matches the pinned vector. If one exists, it returns that pair's `progress()` without executing anything. Only an absent or pending pair is executed. Test that a second `compare` at the same versions changes nothing.

### Nits (non-blocking)
1. **Hand-off to item 7.** `snapshot()` writes receipts into `workspace.work`. But `complete()` and the first `admit()` read evidence from the live `c.work` (`extensions.py:174, 214`). Say whether item 7 calls `snapshot` with a live workspace or copies the evidence in. Otherwise the original pairs will never be in receipt format, and nothing can ever be reused from them.
2. **Stress binding.** "Stress binds case/seed/slot plus its scientific version" does not give the exact JSON that is hashed. Either reuse `run.attack_binding`, which already exists, or specify the dictionary.
3. **`retain_comparison` signature.** Give it exactly, e.g. `roots=None`, a mapping from phase to `Path`, with the default `extension-snapshots/N/...` behaviour.
4. **"Detail containing `error`".** Say "top-level key `error`".
5. **Inconclusive counts as regression.** A G16/G17 inconclusive outcome after an entry pass becomes a regression, and the case retires. The live runner treats inconclusive as "not evidence" and stops without repair (`run.py:2810-2811`). This matches item 5, but the design should say explicitly that this harsher outcome is intended.
6. **G10 attempt reuse.** "G10's adapter may reuse its own validated AttemptSeries" can't work as specified. Retained support is copied under `comparison-support/G10/…`, not to the original attempt paths. Either drop the sentence or say where the attempts are restored.
7. **Heilmeier objective.** The objective is jargon-heavy. Add one plain sentence, e.g. "re-judge the before and after copies of a case with today's rules, so an extension is only counted when the case really got further".

Murphy rows: "supports row 9, closes none" is consistent.

## Elephant response

All three new blockers accepted. Stress comparison writes searches only to work evidence and uses saved case search history for G2. Existing invalid-infra and CaseProblem semantics are retained. Completed same-version pairs are sticky and cannot be rerolled. All seven nits are addressed in the revised contract. No blocker is rejected. The implementation and fresh diff review must verify these resolutions.

