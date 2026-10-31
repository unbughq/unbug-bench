**FAIL.** One concrete blocker is left. B1, B2 (the reviewer path), B3, B4 and M1–M4 are resolved at b95bb1b.

## Blocking

**R1. A replacement try that submits nothing still ends as an infrastructure failure.**
- **Where:** item 5, "G10 evidence semantics" and the `scientific_outcome` order, against `factory/fairness.py:70-72` in `review_attempts`.
- **The conflict:** the order puts "absent submission → no_submission" ahead of "time_limit/call_limit → capped". So a replacement that hits its time or call limit without writing a fix is classed as `no_submission`, not `capped`.
  - The rule "a capped or unknown replacement is likewise inconclusive" therefore never applies to it.
  - The design also says "missing submissions retain their existing bounded replacement path". That path still ends in `raise InfrastructureExhausted('replacement supplied no reviewable fix')`. The same happens to a valid, uncapped replacement that simply chooses not to submit.
- **Why it blocks:** this is row 39's own scenario. A real solver outcome would be counted as infrastructure, retried, and sent to factory-bug routing, which goes against ENGINEERING §3. It is the same problem as B2, just one step before the reviewer is called.
- **Fix (one sentence in the design):** a replacement whose saved execution passes `require_valid` and has no submitted fix returns `None`, i.e. a scientific inconclusive with `verdict_valid:false` and `review_inconclusive:true`. `InfrastructureExhausted` stays only for a missing or malformed replacement row, or an invalid execution.

## Checked against code and found sound
- **B1:**
  - Every named plumbing helper exists in `run.py`. `shred_tree`, `update_case_budget` and `case_budget_boundary` are imported names, so the AST walk hashes their import lines.
  - The existing `SIDE_EFFECTS` set is the obvious place to put the boundary.
  - `calibrate`, `checkpoint`, `strategy_run` and `g3` are explicitly kept as scientific even though they mix in plumbing. The design says outright that edits inside them still invalidate gates.
  - The 9 cached gates in `DEPENDENCIES` match the "nine reusable gates" payoff test.
- **B2:** returning `None` from `review_attempts` already maps to `verdict_valid:false, review_inconclusive:true` in `breadth` and `diagnose` (`fairness.py:150-171`). It never calls `independent_review.review`.
- **B3:** the G10 difficulty threshold is unchanged, and the design says so.
- **B4:** the design states a one-time revocation of old receipts, stale sealed proofs that must requalify, an unknown cost, and that no budget or run is authorized. `sealed_audit.delivery_contract` and `verify_exam` both exist.
- **Fixtures and tests:**
  - Case `case-20261017T125556Z-18681d` is in `invalid-runs-public-cards.json.gz`.
  - `cheat`, `plain`, `reference` and `reset-invalid` are in `invalid-runs-real.json.gz`.
  - Both cited usage tests exist in `tests/factory/test_stream_d_runtime.py:256` and `:298`.
- **Row 39:** the design leaves it open if the retained artifacts can't prove complete closure, as the scope asks.

## Nits
- `family` is a G16 root, but it is imported from `model_runtime`, which the design calls pure plumbing. So only the import line is hashed, and a change to how `family()` maps models won't invalidate G16. That may be intended; say so.
- G16 and G17 are in `repairable` (`run.py:2803`), so an inconclusive caused by capped evidence goes to writer repair. State that this is the intended route.
- The problem statement still says "an easy no-submission currently satisfies difficulty", but that half is no longer changed. Note that it was dropped.

I edited nothing, ran no agents, and did not push or merge. Item 6 and lane 1 were not reviewed.

## Implementation response

R1 accepted and fixed: a retained no-submission replacement is validated as an attempt, then returns scientific inconclusive before execution/review. No execution artifact exists for an absent guard; attempt_summary validates the retained outcome and rejects explicit invalid infrastructure. Missing/malformed replacement rows remain operational failures. Nits accepted: bind the narrow family function separately from model_runtime plumbing, retain ordinary writer-repair routing for G16/G17 inconclusive, and explicitly leave the easy threshold unchanged. No findings rejected.
