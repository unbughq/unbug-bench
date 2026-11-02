**PASS: no open blockers.** This is final design round 2 of 2, reviewed read-only at `cab6a76` against `docs/designs/stream-d-blocking-stress-outcome.md` and round-1 review. It leaves one Major and three Nits. None needs another design round, but the Major should be fixed in the design text and tests before implementation.

### B1 disposition: fixed and verified independently
- **Single computation.** Findings are calculated once: `freshness_only_clearance(result)['blocking']` with the `review incomplete` sentinel removed, before clearance. `cleared_stress` runs only when there are no findings and `freshness_review` or `freshness_review_malformed` is set.
- **Clearance cannot add findings.** `late_recovery.py:114-115` requires `parsed == freshness_only_clearance(original)`, and `run.py:1027-1032` only filters `blocking`. So the cleared `blocking` list is the same list the findings were computed from. If findings start empty they stay empty, and the remaining checks (`complete`, sentinel, unfinished validation, unfinished diagnostic) run on the cleared result. The reasoning holds.
- **The real exclusion path is covered.** When `loop_freshness` excludes a URL but the report has no exact request line, it returns at `run.py:1136` and writes no `-writer.json` or `.clearance.json`. The writer loop then treats the real defect as a finding (`:1623`), the loop ends, and the receipt is marked `exhausted`/`rounds_exhausted` (`:1641-1648`). `package.run` catches only that error (`extension_package.py:430`) and calls `stress()`. Skipping clearance and keeping the original report is therefore correct.
- **Raised freshness stops still propagate, including on resume.** `freshness_unresolved` and `freshness_public_match` are re-raised at `extension_package.py:424-431`. `exhausted` is written only after the last round's `loop_freshness` returns normally. A resumed exhausted receipt raises at `run.py:1196-1200` without calling `loop_freshness` again, so B1's precondition holds after a resume too.
- **The public-match recorder cannot take over the outcome.** An excluded verdict has zero confirmed hits, so `extension_public_match._confirmed` returns None (`:133`) and `public.complete` is False.
- **The real fixture can reach `confirm_hits`.** The practice `case.json` pins `version: 2.19.0`, so the real `loop_freshness` gets past the `pinned_version_unknown` check (`run.py:1085`). Only `confirm_hits` needs to be an authored control.

### Findings

**1. Major: a request-only report with no freshness metadata moves from a scored failure to a permanent hold, and the design wrongly says "keeps".**
- **Where:**
  - design lines 46-47 ("The extra result.blocking condition also keeps … pending, even if complete was asserted");
  - the table row "Unresolved/unverified freshness…";
  - code `extension_package.py:289-297`, `extension_evaluator.py:217`, `run.py:1047,1623`.
- **What happens today:** the report is `complete=True`, its only blocker is an exact request line, and `freshness_review` is absent or `[]`. `loop_freshness` returns early. The writer loop counts the line as a finding and the receipt ends exhausted. Package `stress()` skips clearance and scores a failure (`ok = not blocking`). `extension_evaluator.stress` would also score it as a failure.
- **What happens under the design:** `findings` is empty, `blocking` is not, so the result is `extension_execution_pending`. Each resume repeats this without model calls (`run.py:1196-1200`). `extension_execution_pending` is not a diagnosis trigger (`diagnosis.py:51-56`), so this is a human stop.
- **Assessment:** the parent wants this input left unscored, and that is defensible because the freshness question was never resolved. It is not a wrong score, so it is not a blocker. But it is a behaviour change described as preserved behaviour, it diverges from the evaluator and the writer loop, and the test list covers only the variant with non-empty `freshness_review`.
- **Correction:**
  - Reword "keeps" to say this deliberately changes a currently scored failure into an unscored hold.
  - Add a table row for it: "Request-only blocker, no freshness metadata, complete True, exhausted → `extension_execution_pending`, no outcome (was stress fail)."
  - List the divergence from the evaluator and the writer loop, and this un-diagnosed hold, under Risks.
  - Add an explicit test: authenticated exhausted receipt, `freshness_review` absent and `[]`, direct `package.stress` call, assert `extension_execution_pending` and history still open.

**2. Nit: the negative tests don't say which route they use or which stop to expect.**
- **Where:** the design's Exams section ("Negative midterm…", "For legacy validation-unfinished labels…").
- **Issue:** through `package.run`, these inputs never reach `stress()`:
  - a legacy-label-only report raises `stress_review_unresolved:unfinished_validation` (`run.py:1626`);
  - a sentinel-only report raises `stress_review_unresolved:interrupted_review` (`:1628`);
  - an unfinished diagnostic with no findings raises `stress_validation_exhausted` (`:1632`).
- **Correction:** name the route for each case. For the producer check, call `package.stress` directly with the authenticated receipt and expect `extension_execution_pending`. For the `package.run` check, expect the writer-loop stop above, plus history still open. The completed-legacy-label test stays as N3 required: `completed()` was invoked, the completion marker is present, the parsed report has no defect, and history is open.

**3. Nit: where the findings calculation goes.**
- **Where:** design line 37, "Immediately after attack_report/classify".
- **Correction:** say "after the `result is None` refusal (`extension_package.py:288`)".

**4. Nit: the failure detail for mixed reports.**
- **Where:** the B1 paragraph and "Retention" ("Detail is the exact parsed/cleared report").
- **Issue:** when findings are non-empty and a valid clearance exists for the request lines, the retained detail is the original report. It still contains request lines that were already cleared, so diagnosis may treat them as unresolved.
- **Correction:** none needed in code. Reword Retention to "original report when findings exist; cleared report only on the no-findings path" so the two sections agree.

### Other checks that hold
- **`review_pending is False`:** the real receipt is set to False before `validated` (`run.py:1617`; category path `:1602`). Hand-built receipts in the tests already carry False (`test_late_gate_fixes.py:46`, `test_stream_d_entry.py:71`).
- **Partial output stays unscored:** interrupted calls keep only `*-partial-*` bytes, and `aggregate()` reads only committed result files (`stress_progress.py:72-78`). `validated` is written only after `stress_categories` finishes and `completed()` has run.
- **Validity and money checks unchanged:** `Records.save` still refuses through `_pending` with `InvalidInfra`, and both downstream guards (`next_phase` for a pass, exhaustion for a failure) are unchanged. No money, schema or launch change.
- **Crash replay:** `Records.load` runs first, and `_save_case` re-checks a published outcome directory. One diagnosis ID follows the existing `finalize_accounting` → `record_exhaustion` path, and `_trigger` fires on `extension_incomplete` once an outcome exists, as the existing dispatch tests do. `DIAGNOSIS_ENABLED` stays False.
- **Fixtures:** the `ExecutionTests` and `RuntimeTests` patches (`test_stream_d_execution.py:74-79`, `test_stream_d_runtime.py:86`) can be captured and restored as the design says.
- **Lane 2 boundary:** an exhausted writer receipt still refuses on the actor check, so the rejected-writer case stays with lane 2.
- **Standards:** the Heilmeier items (plain objective, cost, time, risks, exams) and the readiness items (one production function, one test file, one phase) are present. Nothing else is left for the implementer to decide.

### Skipped checks and risks
- No tests were run, as the brief says. Whether the real category engine runs under the reused fixtures, and the ID count from running `finalize_accounting` twice, are inferred from existing tests, not executed.
- Flagged hit or ambiguous rows in the practice `freshness.jsonl` will join the `confirm_hits` rows. I did not check that the authored exclusion control handles them all.
- I did not review the public-match slice, lane 2 (`observe_stress`, unchanged writer) or the parent's integrated suite, as instructed.
- Residual risk: the hold in finding 1 depends on how often attackers write request lines without filling `freshness_review`. That frequency is unmeasured.

## Elephant disposition

B1 independently resolved, no blocker open or rejected. Accept M1 and N1–N3 before implementation: explicitly document the deliberately unscored, un-diagnosed request-only/no-metadata hold (and its divergence from the writer/evaluator), test absent and empty freshness metadata, name direct-producer versus package-run stops, locate findings after the None refusal, and clarify original-versus-cleared retained detail. No third design round; proceed against this passing design and these corrections. Full suites use the shared lock; no rerun of the accepted prior slice.
