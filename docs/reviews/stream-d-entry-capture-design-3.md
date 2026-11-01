**Verdict: PASS.** No blocking findings are left. Both round-2 blockers are fixed, and the 2 optional items and 7 nits from round 2 hold up against the code. Six non-blocking nits remain below.

I edited nothing and ran no workers, live calls or subagents. Reviewed at worktree t3-4ac6b632 @6afceac in Mode: REVIEW, using the zoom_out, design_critic and implementation_readiness personas with heilmeier-standard and implementation-readiness-standard. I read `docs/ENGINEERING.md`, the three persona files, the three standards, the design and both earlier reviews. Later binding amendments override earlier text.

## Round-2 blockers

**B-1 (an inconclusive review counts as a failure): fixed.**
- `fairness.breadth` (G16) returns `ok=False` with `verdict_valid: False` and `review_inconclusive: True` when there are no counts (`fairness.py:168-170`).
- `_pending` treats inconclusive or invalid-verdict results as pending only when `ok` is true. It always treats `error` or `execution_valid is False` as pending (`extension_compare.py:89-93`).
- So under the design:
  - The G16 result gets saved as a failure record.
  - `pipeline.run` stops and returns normally.
  - `validate_and_repair` returns, because of its `review_inconclusive` check (`run.py:3028-3029`).
  - `closed.json` gets written, and entry reports G16 as `fail`.
- An error-shaped result is pending. `observe_gate` doesn't save it, so no close marker is written and entry is pending.
- The test plan now matches the code, and G16/G17 are labelled correctly.

**R1 (late-gate rehearsal was missing from the exclusions): fixed.**
- `late_rehearsal.py:68` sets `audit_gates`, and `run.py:3056` removes it after a repair.
- The exclusion now reads `getattr(args, 'late_gate_rehearsal', False)`, so the check no longer depends on `audit_gates` and covers both traversals.
- The test after `audit_gates` is removed is specified.
- I checked every `run_gates` caller:
  - `sealed_audit.py:212/229` runs under `audit_fairness` or `rehearse_only`, both excluded.
  - Package `run` passes `around_gate`/`replay_gate`, also excluded.
  - That leaves `validate_and_repair` (`run.py:3023`) as the only eligible caller, and it always runs `mark_gates` first.
- Keeping `skip_build` eligible is fine. The dispatcher's mode refusal (`run.py:3320-3322`) applies when an extension runs, not when the entry is captured.

## The newly specified items

- **Hash equality (pointer == closed == `case_hash` of the copy): correct.** `case_hash` covers only case files and ignores `freshness.jsonl` (`run.py:884-891`). Gates must not change it; package capture already refuses if they do.
- **Close bookkeeping and the stopped/infrastructure guard: sound.**
  - `run_validity.retry` re-invokes only after an exception (`bin/run_validity.py:82-99`), so a successful save is always the last attempt.
  - An infrastructure crash goes through `stop_infrastructure`, which sets `c.stopped` and `infrastructure_gate`. `run` still returns normally (`gate_pipeline.py:155-163, 192-196`), so the guard is needed.
  - The card is rebuilt fresh in each process (`run.py:3269`), so an old `infrastructure_gate` cannot wrongly suppress the close marker.
- **Mapping `_Changed` to pending: correct.** `_Changed` is a `RuntimeError` (`extension_compare.py:36`), raised at `:217/221/228`. Mapping it to pending matches the existing package handling at `:307`.
- **A G3 record without a worker count holds pending: correct.** `Records.load('G3')` refuses unless `bench_workers_effective` is a positive int (`extension_package.py:84-86`). This overrides line 98's "a real failure is terminal" for G3 only.
- **Hoisted stress-binding helper: correct.** It is the nested `scientific()` function (`extension_package.py:238-243`). Moving it to module level changes no behaviour, and `attack_binding` (`run.py:961-968`) includes the worker settings that it strips.
- **Symlink labels: correct.** `extensions._writer_json` goes through `diagnosis._input_bytes`, which already refuses a symlink anywhere on the path inside the base folder (`diagnosis.py:520-531`). Reusing it satisfies the "all parents" requirement with no new code.
- **Timing obligation: fine** as a recorded activation item. Nothing is enabled.
- **Scope: right for this increment.** It covers first-entry capture only and stays pending whenever any history exists. Isolated comparison and terminal outcomes are named as the next increments. `diagnosis_dispatch.py` is untouched and activation stays false.

## Nits (non-blocking)

1. **Exact key sets.** Write out the key sets for `current.json` and `closed.json`, for example `{schema_version, observation_id, round_number, case_sha256}` and `{schema_version, observation_id, case_sha256}`. Lines 53-54 say `round_number`, while M5 and round 2 say "pointer round" and `pointer.case_sha256`. Pick one name.
2. **Which `BudgetError` labels entry maps to pending.** Line 220 says "BudgetError evidence labels". List them:
   - `extension_reservation_mismatch` (raised by `_writer_json`);
   - `extension_snapshot_changed` (raised by `refuse`);
   - `extension_comparison_pending`.

   Also state that the job-authority and history checks sit outside that try block, so they are never swallowed.
3. **How the G16 test reaches G16.** Running a real `validate_and_repair` to G16 needs G1–G15 passes, and the `audit_gates` shortcut is excluded. State that G1–G15 are authored pass controls, by substituting `pipeline.check` per gate as M6 does for G1–G3. Also say whether "entry fail receipt" is asserted with `Records.load('G16')` or through `entry()`. Going through `entry()` also needs a stress pass and saved records for every earlier stage.
4. **Symlink at the start of `observe`.** A symlinked `entry-records` folder makes `observe` raise `BudgetError('extension_snapshot_changed')` before any gate runs. That is a new ordinary stop, but only for a tampered work folder and only once capture is enabled. Say this is accepted, and test that it stops the case rather than retrying.
5. **Old snapshot copies.** M1 deletes old `entry-records/<uuid>` folders, but not the `comparison-support/<stage>/entry-records/<old-uuid>/…` copies an earlier `entry()` call made. These grow only once per diagnosis call, not per traversal. Either note this or clear `comparison-support` at the start of `entry()`, as package rebasing does (`extension_compare.py:298`).
6. **Leftover superseded text** (round-2 nit 7). Line 98 ("a real gate failure is terminal") still conflicts with the G3 hold, and lines 53-54 with the pointer key names. The precedence rule settles both, but deleting the old wording would help the implementer.

**To pass:** nothing more is required. The nits are optional.

## Disposition

Accepted PASS. Implement the approved first-entry subset. No blockers remain; optional key/label/test-boundary clarifications are recorded in the design before implementation.
