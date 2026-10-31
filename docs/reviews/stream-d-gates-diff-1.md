**PASS.** I found no blocking issues. Design-2 R1 is fixed, and every in-scope item matches the final Item 5 design, including the Review-1 limits and the Review-2 resolution.

## Design-2 R1: fixed
In `factory/fairness.py:77-84`, a replacement try now goes through these checks in order:
- A missing or malformed replacement row still raises `InfrastructureExhausted`.
- If the row is present, `attempt_summary(rows)` validates it. An invalid row or an explicit invalid-infra row raises.
- If no guard was submitted and the row says `guard_submitted: false`, the function returns `None`. This happens before any execution or reviewer call. `breadth` and `diagnose` then record `verdict_valid:false` and `review_inconclusive:true`.
- If no guard exists but the row doesn't say `false`, it raises `InvalidInfra`.

This holds whether or not the try was capped, because the check doesn't look at `stop_reason`. `tests/factory/test_invalid_runs.py:506` was flipped from expecting `InfrastructureExhausted` to expecting an inconclusive result. That test confirms the replacement is bought once and no reviewer is called.

## In-scope items checked against the design
- **Per-gate versions:**
  - `gate_state.scientific_version` covers every key in `run.GATES` plus `stress`.
  - It removes case, seed, slot, `UNBUG_FACTORY_SLOT`, worker count and concurrency.
  - It keeps prompts, models, roles, `model_science` and source mode. `model_science` binds `model_router.family`, the same function `run.py` imports through `model_runtime`, plus `model_effort`.
  - The cache-file digest is gone, and `gate_state.py` is no longer in `judge_dependencies`.
  - `SIDE_EFFECTS` matches the named plumbing helpers. `model_call` is no longer a G16 root and `opencode` is no longer a stress root.
  - `MODEL` is now calibration only, and `registry` is out of `STRATEGY`.
  - New receipts store `scientific_version`, and `load` checks it.
- **Old receipts:** they fail the full-inputs comparison because the `cache` key is removed and the `prompt`/`prompts` and runner bindings changed. Old calibration identities fail `compatible_identity` because the new `model_science` field is missing. So old work must requalify once, as the design says.
- **Calibration outcomes:**
  - `scientific_outcome` follows the design's order exactly. An unrecorded stop becomes `unknown`.
  - `commit` stores the outcome. `attempt_summary` recomputes it and rejects a conflicting label.
  - The aggregate has exactly the five outcome keys.
- **Capped or unknown attempts before review:** `review_attempts` returns `None` before calling the reviewer. `verdict` refuses a `wrong_fix` label unless the try is a `demonstrated_failure`.
- **Strategy receipts:** `strategy_run` (version 5) now uses `gate_state.inputs(G13 or G15)` plus the strategy name. `bench_manifest` and the whole-source hashes are removed. G14 doesn't call `strategy_run`, so leaving it out of the mapping is correct.
- **Tests:**
  - `tests/factory/test_scientific_receipts.py` shows that a plumbing edit keeps all 9 `REUSABLE` receipts and the calibration identity, and that tampering with evidence invalidates them.
  - An edit to G4's own code changes only G4's version.
  - Changes to prompt, model, `family`, source mode or judge environment change the version.
  - The capped `wrong_fix` case ends inconclusive with no paid call.
  - Cap metadata in these tests is clearly labelled as authored.
- **Suite record:** the uncompressed run-2 log hashes to `999900c3…abc14`, which matches the record, and ends "156 test scripts run; 0 failed."
- **Row 39:** it stays OPEN. `docs/murphy-register.md` is unchanged in this diff, and the design note, the test docstring and the suite record all say so.

The deliberate choices you listed are stated in the design and are not findings: conservative mixed executors, the unchanged G10 difficulty threshold, and one-time requalification.

## Nits (none blocking)
1. **Early `return None` inside the loop** (`fairness.py:108-109`):
   - **Stale receipt:** if an attempt's `execution.json` was just rewritten by the repair branch and the attempt turns out capped or unknown, the function returns before `atomic_results(results.json, repaired)`. The rewritten workspace no longer matches the row's `artifacts` digest. A later same-identity `completed_attempts` would quarantine that try and re-buy it.
   - **Lost acceptance:** in G17's `invalid_execution` path, a capped earlier try ends the review as inconclusive even when a later try would have repaired into a solve and been accepted.
   - **Why it's minor:** both cases fit the design's wording, and the inconclusive result goes to writer repair, which changes the case identity anyway.
   - **Optional fix:** check eligibility after the loop, or persist the repaired rows before returning.
2. **Untested branches:** nothing tests `'replacement receipt missing or malformed'` or `'replacement submission evidence missing'`. The R1 test also only uses a capped (`time_limit`) no-submission, not the uncapped completed one R1 described. It's the same code path, but each would be a cheap test to add.
3. **KeyError:** a replacement row without `workspace` raises `KeyError` at `fairness.py:80` instead of the operational exception.
4. **Stale design text:** the Item 5 "Problem and change" paragraph still says "an easy no-submission currently satisfies difficulty". Only the Review-2 resolution text says the threshold is unchanged.

I edited nothing, ran no agents and didn't push or merge. Item 6, lane-1 retry/routing, diagnosis enablement and live cases were not reviewed.

## Implementation response

Accepted PASS. No blocking findings remain. The full suite record was committed before this review. No implementation changed after the passing suite.

Nits 1–3 are retained as optional follow-up: early inconclusive return can leave repaired evidence uncommitted or miss a later repaired solve; malformed replacement branches lack dedicated coverage and a missing workspace raises KeyError. The report assesses these as non-blocking under the reviewed writer-repair route. They are not claimed fixed by this increment. Nit 4 is clarified in the design's opening paragraph: the existing easy threshold is intentionally unchanged.

Row 39 remains open; no real capped-submission per-attempt lifecycle artifact was available. No rows were closed, no real cases launched, and item 6 was not started.
