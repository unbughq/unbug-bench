**Verdict: BLOCK.** There is 1 blocker and 1 required fix. The rest is optional. I edited nothing, made no paid calls and started no subagents. Reviewed at worktree t3-4ac6b632 @6afceac, Mode: REVIEW, using the zoom_out, design_critic and implementation_readiness personas with heilmeier-standard and implementation-readiness-standard.

## How the round-1 amendments hold up against the code

- **B1 (capture can't trigger paid re-runs or change stop labels): holds.** `gate_attempt.execute` retries only when the callable itself raises. The "completed" publish happens after it returns, outside the retry (`gate_attempt.py:34-48`). So a capture that calls `invoke()` once, outside its own error handling, and returns the original `(ok, info)` cannot re-run a gate or change a stop. The catch list covers what capture-side code can actually raise: `refuse()` raises BudgetError, `save` raises InvalidInfra, plus OSError, ValueError, KeyError and TypeError (`extension_package.py:37,90,163,177,192,207`). Dropping replay and restore also removes the second-invocation path.
- **Close marker: correct, with one subtlety.** After an infrastructure exhaustion, `pipeline.run` still returns normally (`gate_pipeline.py:194-196`). The rule "every invoked stage has a valid saved record" still suppresses the marker, but only if the bookkeeping is per stage across attempts (see nit 1).
- **Pointer before gates: correct.** `run_gates` runs outside `gate_attempt`, so a pointer I/O error can't cause a paid retry.
- **B2 (when capture is on): mostly correct.** Missing one mode; see R1.
- **M1 (old roots deleted): correct.** Checkpoints tar the whole work directory, so bounding retained roots to one matters.
- **M2 (entry works on a copy): correct and necessary.** `snapshot` computes the version vector before calling the evaluator (`extension_compare.py:176`). Versions therefore have to be pinned after the preliminary G3 load sets `bench_workers` on the copy, as M2 says. `_configuration` then stays stable, because the G3 load writes the same value again.
- **M3 (partial work held as pending): fine** as a named, conservative hold.
- **M4/M5 (stress and pointer checks): correct.** `validate_and_repair` calls `stop_defect` right after `run_gates` with no writer call in between (`run.py:3032-3034`). So rounds-exhausted cases keep the same case hash and `builder_rounds`, and entry can use them. Lane 1 calls `inherit_recovery_history` before `admit_extension` (lane-1 `run.py:3312`), so `builder_rounds` is present when entry checks the pointer round.
- **M6 (fixtures): the fixtures exist.** All four named files are in `tests/factory/fixtures/`, and `test_extension_compare.py` already uses the saved plain/reference transport. One test contradicts the code; see B-1.
- **Lane-1 seam: preserved.** Lane 1 calls `getattr(extension_package, 'entry')` and then `extensions.propose(c, entry(c, r))` (lane-1 `diagnosis_dispatch.py:470-473`). Raising `extension_comparison_pending` on any history fits that. There are no `diagnosis_dispatch.py` changes.

## Blocker

**B-1. An inconclusive fairness review is a scored failure, not a pending result. The M6 test (lines 236-238) can't pass as written.**
- `fairness.breadth` (G16) and `fairness.diagnose` (G17) both return `ok=False` with `review_inconclusive: True` when there are no counts (`fairness.py:168-170, 193-195`).
- `_pending` flags inconclusive only when `ok` is true (`extension_compare.py:93`). The existing test `test_classifier_matches_runner_and_preserves_inconclusive_failure` (`test_extension_compare.py:194-212`) asserts the stage is `'fail'`.
- So under the amended design, `observe_gate` saves a fail record and `pipeline.run` breaks and returns normally. `closed.json` gets written, and entry returns a snapshot whose frontier is that failed stage, not `extension_comparison_pending`.
- Round 1's B1 had the same false premise: `save` never raises InvalidInfra on this shape. The other refusal paths it listed are real, so the observational capture mode is still the right fix.
- The text also mislabels `fairness.diagnose` as G16; it is G17, and `breadth` is G16.

Decide one of these:
- **(a) Recommended.** Keep the existing classifier: an inconclusive review is a bound failure. Change the test to assert one review, the ordinary tuple unchanged, `validate_and_repair` returning, and entry returning that stage as `fail` with `review_inconclusive` in its detail. For a pending case, use an `'error'` or `execution_valid: False` result instead. This adds no new rule. Note that `validate_and_repair` deliberately doesn't send "unknown" to the writer (`run.py:3028-3029`). Lane 1 owns what feedback an admitted extension's writer receives.
- **(b)** Hold inconclusive results as pending at capture. This needs a capture-only rule that diverges from `extension_compare._pending` and its existing test. Not recommended.

## Required fix (cheap, belongs with the blocker fix)

**R1. The "exact" B2 eligibility check misses late-gate rehearsal.**
- The dispatcher's own mode guard excludes `late_gate_rehearsal`, `statement_only`, `skip_build` and `salvaged_from` (`run.py:3320-3322`). B2 omits `late_gate_rehearsal`.
- `late_rehearsal.run` sets `c.audit_gates` (`late_rehearsal.py:68`), but `validate_and_repair` pops `audit_gates` after a repair (`run.py:3056`). The second traversal then becomes eligible.
- Once diagnosis is enabled, that would force G10 to run serially. That defeats the rehearsal's `rehearsal_interrupt_g10` overlap exercise, whenever a rehearsal runs as a factory job.
- Fix: add `args.late_gate_rehearsal` (read via `getattr`, default False) to the check, and add one more independent exclusion test.
- The other three need nothing: `statement_only` stops before gates, `salvaged_from` applies only to non-factory jobs, and capturing a `skip_build` gate-only continuation is legitimate.

## Optional (non-blocking)

**O1. The cost of running G10 serially is unquantified.** The one real saved card with G10 timing (`invalid-runs-public-cards.json.gz`) shows G10 at 144.4 of 148.1 gate-minutes, and that was overlapped. Add "enabling capture serialises G10 for every live case, measured cost X" to the activation obligations in `stream-d.md`, so the activation decision has the number. Serial is still the right choice for this increment. Without it, `project(c.card)` could race a concurrent G10 card mutation and raise a RuntimeError that is not in the catch list, which would turn back into a gate retry.

**Nits:**
1. **Close-marker bookkeeping.** Mark a stage "not saved" if its last attempt didn't save. As a second check, skip `closed.json` when `c.stopped` is set or `infrastructure_gate` is present after `run` returns.
2. **Which case hashes entry compares.** Say whether entry requires pointer hash == closed hash == `case_hash` of the copy, or only closed == current.
3. **`_Changed` is unmapped.** `snapshot` can raise `extension_compare._Changed` (a RuntimeError), which isn't in the entry refusal mapping. Either map it to pending or state that it propagates.
4. **A G3 failure record holds pending.** A G3 failure record without `bench_workers_effective` fails `load` and therefore holds pending (`extension_package.py:84-85`). State this, and that it's accepted.
5. **The stress-binding normalisation is a nested function** inside package `stress()` (`extension_package.py:238-243`). Say "hoist to module level and reuse".
6. **Name the label** M1 uses when it refuses a symlinked `entry-records`.
7. **Clean up the superseded text.** Delete the original lines 39-41 (package `capture`, publication-ack replay), 45-48 and 57-59 instead of overriding them. Name the test file. Move the plain goal (lines 247-249) to the top, per the Heilmeier standard.

**To pass:** resolve B-1 (option (a) is recommended) and R1. Everything else is optional. After that, first-entry capture can stand alone as this increment.

## Disposition

Accepted B-1 option (a) and R1. Keep the existing classifier and add the late-gate-rehearsal exclusion. Round-2 binding decisions in the design also resolve optional receipt/hash/error bookkeeping details. No implementation yet; fresh review required.
