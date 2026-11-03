**BLOCK.** Design round 2 still has one blocker. It is the last permitted round, so it goes to the parent. The B2 and B3 fixes hold. B1 does not: the replacement stop it names can't be produced by real code.

## Blocker

**B1′. In a fresh batch job, a gate's budget check can never stop with `budget_exhausted`.**
- **Where:** the "Partial entry, progress and completed replay" row (design line 113). Every other branch builds its first exhaustion on this one: extension 2, the factory-bug return and cap, the extension cap, rejected-writer, not-converging, malformed and deadline. The "Ordinary factory bug" row also says only "real exhaustion/finalization" without naming one.
- **Why it can't happen:**
  - The gate pipeline's budget check is `case_budget_boundary` (`factory/run.py:915`, called at `factory/gate_pipeline.py:178`).
  - In a batch job it calls `require_case_budget` with the job's money authority (`factory/model_runtime.py:289-291`).
  - That branch only ever raises `money_wait` (`factory/budget.py:714-717`). `budget_exhausted` is raised only on the non-batch path (`budget.py:721`).
  - I probed this offline. With money authority the result is `money_wait`; without it, `budget_exhausted`.
  - `money_wait` does not trigger a diagnosis (`factory/diagnosis.py:52`). This is exactly what round 1 found.
- **Why it's a blocker:** the only way to get the named stop is to stub the budget check. That breaks the design's own "Never stub … limits" rule and is the "synthetic exhaustion" the design says it refuses (line 43). Otherwise the implementer has to invent the first-exhaustion mechanism.
- **Fix (design edit only), pick one:**
  - **(a) Keep the partial entry, G5 never scored:** the initial stop is `infrastructure_exhausted` at G5. Two authored InvalidInfra child-start failures run through the real `gate_attempt`, and `stop_infrastructure` marks G5 `invalid-infra` (it is not pass/fail, so `entry_prefix` treats G5 as unreached). Note that `run_gates` returns normally with `c.stopped` set rather than raising.
  - **(b) G5 scored as a fail:** real G5 plain rejects, then the ordinary repair writer's reservation in `pending_call` fails the ordinary limit and raises a real `budget_exhausted` (`run.py:444-446`). That needs saved usage above the ordinary limit minus the reservation, and the driver must call `validate_and_repair`. This loses the "partial missing suffix" recovery claim.
  - Either way, name the same mechanism for the ordinary factory-bug branch's first exhaustion.

**Three lines for the parent:**
1. A fresh batch job's gate budget check raises only `money_wait` (`budget.py:714-717`), so the design's first stop, `budget_exhausted` at G5, is unreachable without the stub the design forbids.
2. Every branch depends on that first exhaustion.
3. Decide between (a) `infrastructure_exhausted` at G5 through real `gate_attempt` (G5 stays unreached) and (b) a real ordinary-limit refusal on the repair writer after a real G5 fail. Then the design can be implemented.

## Round-1 fixes, checked against the code
- **B1:** not fixed. See B1′. The diagnosis triggers it lists are correct.
- **B2:** fixed. The real/authored table matches `EntryTests.saved_execution_controls`: the suffix-case swap, authored G1, and real G4 and G5 using `execution('plain')` / `execution('reference')`. Real G1 appears only in the G1-rejection row.
- **B3a:** fixed. The initial stress receipt is explicitly authored and matches `EntryTests.stress`. Extension writer and stress runs go through the real `_invoke` seam and `pending_call`.
- **B3b:** fixed. On a same-batch hold, `resume_factory_bug` returns False (`diagnosis.py:526`). After a cross-batch admission, a state that isn't close-to-passing makes `_dispatch` return False (`diagnosis_dispatch.py:311-313`).
- **B3c:** fixed. The error mappings match main at `run.py:3416-3437` exactly.
- **M1:** done. It states it doesn't close `new-stream-d-current-comparison-1`, and why.
- **M2:** done. File paths are given.
- **M3:** verified. `job_config.install` calls `job_authority.read`, which raises `BudgetError('retired_batch_bound')`. `BudgetError` is a `RuntimeError`, so it gets past both `except` clauses.
- **M4:** verified. `restore_ledger.install` writes the restore-scorecard and restore-accounting files, and `install` builds the history entry from the delivered config's SHA.
- **M5:** done. It sets a 1200 s target for the integration method and records actual time against the full-suite budget.
- **Retired labels:** the seven are exactly the current-schema `retired_*` labels in production, and the stated exclusions are correct.

## Optional findings (not blocking)
- **O1. Resume driver steps left out.** Main also runs `inherit_recovery_history`, which copies `route_receipts` (factory-bug evidence) and ordinary-limit checks, and `pick_models` before `admit_extension`, which needs `c.models['builder']`. It also builds a fresh card and checkpoint card on each resume. Say whether the driver does each of these.
- **O2. Factory-bug cap.** Say that each of the four findings is produced the same way as the hold-and-return branch: a comparison InvalidInfra crash after a returned extension.
- **O3. Nit:** "Use the real public_progress publisher with temporary SEALED" appears twice (lines 85-86 and 96).

This was read-only: I made no edits, merges, pushes or network/model calls, and started no workers or subagents. The only probe was the offline `require_case_budget` call above.

## Writer disposition

B1′ remains open for parent decision under the two-round cap. Recommend option (a): two authored InvalidInfra failures at G5 through the real gate_attempt and stop_infrastructure path, leaving G5 invalid-infra/unreached and finalizing a genuine infrastructure exhaustion. Use the same initial mechanism for ordinary factory-bug diagnosis. No implementation or round 3. Optional O1–O3 are recorded for the parent-approved disposition.

