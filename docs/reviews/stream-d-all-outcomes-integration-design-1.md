**BLOCK.** Design round 1: three blockers, each fixable by editing the design. No production change is needed.

I read the personas (zoom_out, design_critic, implementation_readiness) in Mode: REVIEW against heilmeier-standard.md and implementation-readiness-standard.md, then checked the design against the code at 53a9eab. I ran two offline probes; scripts are in `/tmp/goldfish-probe`, outside the repo. Nothing in the worktree was edited, and no workers, network or model calls were used.

## Blockers

**B1. The partial-entry branch can never get a diagnosis.**
- The design stops the case with `money_wait` at G5, then expects a close-to-passing diagnosis.
- `money_wait` does not count as an exhaustion. `diagnosis._trigger` (`factory/diagnosis.py:51`) accepts only budget_exhausted, stress rounds exhausted, infrastructure_exhausted, malformed output exhausted, freshness evidence unavailable and stress_validation_exhausted.
- So `record_exhaustion` never queues a diagnosis. `carry_context` then returns False, and `dispatch` returns False, which is the ordinary path.
- Every later branch builds on this one (extension 2, the factory-bug return, the extension cap), so they all fail with it.
- **Fix:** name a stop that does trigger diagnosis and still leaves G5 unreached, for example `budget_exhausted` raised at the G5 budget boundary. Then assert that `diagnosis_state` is pending and G5 has no pass/fail on the card.

**B2. No saved case passes both real G1 and real G5.**
I probed `run.g1` and `run.g5` with saved `checkpoint` bytes:

| Case file | Real G1 | Real G5 |
| --- | --- | --- |
| practice `case.json` | passes | `CaseProblem` (marketplace observations absent from the judge) |
| suffix-case `case.json` | fails (ingredients block / app pin) | passes (`reference`, keys 5/5) |

- The design says "G1 uses the practice contract; G4/G5 use invalid-runs-real" for every branch. The partial-entry, extension-cap and factory-bug-return branches all need G1 to keep passing while a later outcome passes real G5.
- With both gates real, the comparison sees G1 go from pass to fail and returns `regression`, not `progress`.
- The existing precedent, `EntryTests.saved_execution_controls`, swaps in suffix-case and makes G1 an authored control.
- **Fix:** add a per-branch table saying which gates are real and which are authored. Real G1 should only appear where G1 is the rejecting check, or on a practice tree that never reaches a real G5 pass. Name `execution('plain')` / `execution('reference')` and the suffix-case `case.json` swap explicitly.

**B3. The test driver leaves three decisions to the implementer.**
- **(a) Where the first writer and stress pass come from.** The driver starts at `run.run_gates` and never calls `build()`. Yet the branches need a completed stress receipt in `attack-state.json` with `round == builder_rounds`, the real `attack_binding` and a gate marker.
  - Either it comes from a real `write_and_attack`, with model answers fed through `_invoke`, which is a call the driver doesn't list.
  - Or it is authored like `EntryTests.stress()`, which is not in the design's list of allowed authored boundaries.
  - Choose one and add it to the authored list if it's the second.
- **(b) The ordinary factory-bug resume is never tested.**
  - This is a first exhaustion diagnosed as factory_bug on a case with no extension: hold, then a fixed release in a new batch, then resume. `_dispatch` returns False and production goes back to ordinary `build()`/`validate_and_repair`.
  - The design names this False return but no branch runs it, and it doesn't say what the driver does on False.
  - The brief requires factory_bug hold/resume on fresh cases. Add a subtest: real hold, cross-batch install, then real `dispatch` returns exactly False, with `factory_bug_resume_count == 1`, diagnosis state cleared, and no admit/package/writer calls. Label the ordinary build after that as covered by existing build tests.
- **(c) Copying main's error handling.** The driver says it copies main's handling for `BudgetError`. It should name all three cases it must reproduce:
  - `FactoryBugHeldWait` sets `factory_bug_held` and `factory_bug_wait_reason`;
  - a provider wait goes through `write_provider_wait`;
  - any other exception, including `InfrastructureExhausted`, takes main's `except Exception` path.

  Otherwise the branches through gate_attempt and the Evaluator depend on what the implementer guesses.

## Optional findings (not blocking)

- **M1. Name the Murphy row this exam proves.** Row `new-stream-d-current-comparison-1` (a factory-bug resume after an extension loses its comparison target) is still open. The factory-bug return branch is exactly the integrated chain that `test_stream_d_resume_target.py` says it defers. The design should say whether this exam closes that row or why it doesn't, not just "supports 9/13, closes none".
- **M2. Ambiguous helper names.** There are two `InputTests` classes (`tests/factory/test_stream_d_inputs.py` and `tests/tools/test_qualify_batch_inputs.py`) and two `ResumeTests` classes (`transition` lives in `test_stream_d_held.py`, not `test_resume.py`). Give the file paths.
- **M3. Batch-deadline branch.** The clock is authored but isn't in the authored-boundary list. Also, `retired_batch_bound` comes from `job_authority.read` inside `job_config.install` on resume, before `dispatch` runs. The branch should assert it there.
- **M4. Copying `ResumeTests.transition` through real `install`.** That helper writes `config_sha256='c'*64` straight into the job-money history and sets manifests by hand. Real `job_config.install` recomputes the history entry from the delivered config sha and requires `restore-accounting.json` / `restore-scorecard.json`. Say that only the manifest/carry_from shape is copied, and that the history row comes from `install`.
- **M5. No runtime estimate.** One method runs five extensions with Evaluator comparisons plus three cross-batch factory-bug cycles. Give a midterm runtime number so the 7200 s suite budget is checked before the final run.

## What checks out

- **Retired labels:** the seven current-schema labels match production exactly. `retired_import_*` is only set during legacy import (carry_over), `ttl_retired` is a worker lifetime stop, and `retired_without_output` is only a batch_status display flag, not a stop. None of these needs an exam branch.
- **Branch feasibility:**
  - The extension frontiers G16, G8, G9, G6, G13 are in increasing order in `GATES`.
  - The extension limit is checked in `admit_extension` before `entry` is called.
  - The factory-bug cap fires when 3 resumes exist and a new finding has none, before model work.
  - A comparison that crashes twice raises `stress_validation_exhausted`, which does trigger diagnosis.
  - The per-batch opt-in is read only from the installed manifest.
- **Missing-proof limits:** the cases that must stay `extension_comparison_pending` are stated honestly.

## Writer disposition

B1–B3 accepted. The design now uses budget_exhausted before G5, names each branch's real/authored gates, explicitly authors only the initial ordinary stress receipt, adds ordinary factory-bug hold/resume, and specifies main's exception mappings. M1–M5 are addressed with the Murphy closure boundary, exact fixture paths, real-install deadline stop, authenticated history production and a timed midterm. Request round 2; no implementation yet.

