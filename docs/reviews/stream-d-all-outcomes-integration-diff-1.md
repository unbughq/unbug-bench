**PASS.** Diff round 1 of 2 found no blocking findings. Six optional findings follow.

I reviewed range `84a5649..dc20f2b`, plus the docs-only head `13b0a67`, in the worktree at `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-4ac6b632`, branch `t3/stream-d-gates`. I read `docs/ENGINEERING.md` and the `zoom_out` and `implementation_readiness` personas in Mode: REVIEW, against `implementation-readiness-standard.md`. I compared the code with the design, including its "Parent-approved after round 2" section, both design reviews and the report.

## Blockers

None.

## Optional findings

- **O1. Resume order differs from main.** `Lifecycle.restore` calls `job_config.install` and then `inherit_recovery_history`. Main (`factory/run.py:3329` then `3352`) runs them the other way round. It also skips `authenticate_gates`, `record_founder_decisions` and the explicit `carry_context` before dispatch. I checked and none of this changes behaviour today:
  - `install` only reads `terminal_stop` from the card and `batch_release_sha256` from the checkpoint card, and `inherit` sets neither.
  - `factory_job` is already true from `args.batch_release_sha256`.
  - `_dispatch` calls `carry_context` itself (`diagnosis_dispatch.py:308`).
  - The cards have no `gate_continuation`.

  Matching main's order, or adding a comment saying why it differs, would protect against future changes.
- **O2. The G2 `money_wait` raise is authored.** In the interrupted-freshness branch, `Lifecycle.evaluate` (lines 234–236) raises `money_wait` itself. The real code is main's handler, which turns it into `terminal_stop=money_wait` with no diagnosis queued. This matches the parent's clarification and the branch claims only a refusal. But the report lists the branch without saying the raise is authored, so the external-boundaries paragraph should name it.
- **O3. The fourth cap resume doesn't directly prove "before model/package work".** On `index == 3`, `build` and `validate_and_repair` are forbidden, and the `retired_factory_bug_limit` label rules out a completed package. But `pending_call` and `writer_request` are not forbidden there, and `model_calls` is not compared before and after. A one-line assertion would close that.
- **O4. Completed-package replay checks writer, stress and evaluator, but not the ledger.** `replay_package` asserts that `model_calls`, the snapshot tree and `diagnosis_state` are unchanged, and that every reservation is settled. It doesn't compare `invocation_reservations` before and after, which `replay_retirement` does. That is weaker than the design's "no extra reservation" wording, though forbidding `write_and_attack` makes a new reservation unlikely.
- **O5. Two commits instead of one.** The design says "One test/docs implementation commit", but the work landed as `4f0a517` plus `2c9e9af`. The second commit only adds guards: `run_gates` is forbidden after rejected or terminal stress, and the rejected branches assert `model_calls == ['builder-9']`. It removes no assertion.
- **O6. Shared-host timing risk.** The focused cap branch alone took 1198.75 s. The suite runner has no per-script timeout, so the exam's runtime under host load is covered only by the 7200 s budget for the whole suite. Recording the 1031.8 s measurement is enough for now.

## Evidence checked

- **Suite record.** The `.json` names head `dc20f2bebde9ab0db290d9b3205554fd7e9a096d` and tree `f3d5f816709ac5c6694f2c7aa9cac3fdc0cc4af6`, and `git rev-parse` reproduces both.
  - `log_sha256` `ed4c228d…d9d0` matches `shasum` of the committed log.
  - The log ends with "184 test scripts run; 0 failed." and `exit 0`, and it has 184 `==` script headers.
  - The command is a plain detached `nohup lockf /tmp/unbug-suite.lock`, with `timeout_scope` set to `after_lock_acquisition` and 7200 s. `run_seconds` is 2559.1 and the queue took 0.3 s.
  - The integration section lists all 21 branches with per-branch seconds and "Ran 1 test in 1031.829s OK". The cap trace reads resume count 1, 2, 3, then 3 at the fourth finding.
  - The killed run `184135Z` is marked non-qualifying (exit 143, scripts null). `13b0a67` changed only its `interruption_reason`, its sha is unchanged, and it doesn't count as a failure.
- **Scope.** `git diff 84a5649 dc20f2b -- factory/` is empty. The only test change outside the imported runner (`tests/run.py`, `tests/tools/test_run_slots.py`) is the new file. No existing test was modified and the Murphy register is untouched. `13b0a67` touches only docs and reports.
- **First exhaustion (B1′ option a).** Real G5 runs inside the real `gate_attempt` with `run.checkpoint` raising `InvalidInfra`. `start()` checks the expected outcome:
  - `run_gates` returns `None` with `c.stopped` set and terminal stop `infrastructure_exhausted`;
  - G5 is `invalid-infra` and was executed exactly twice;
  - `diagnosis_state` is pending;
  - there is no `closed.json` and no G5 `record.json`.

  The ordinary factory-bug branch uses the same mechanism. The only replaced gate seam is `pipeline.evaluate`, whose default is a plain `run.gN` lookup (`run.py:913`).
- **Driver.** `finish` reproduces main's exception branches exactly (`run.py:3410-3437`) and always runs `finalize_accounting`. `label()` rejects any `error` or `cleanup_errors` and any unsettled reservation, so an unexpected exception fails the test. Each resume builds a fresh card and checkpoint card, delivers the config with its real SHA, runs the real `restore_ledger.install` (through `install_receipt`) and `job_config.install`, then `inherit_recovery_history`, real `dispatch`, `pick_models`, `admit_extension` only on exactly `int 0`, and real `package.run`. A `False` return is treated as the ordinary route.
- **Factory bug.**
  - The ordinary branch shows hold, then same-owner replay still held, then a cross-batch resume that returns `'ordinary'`, with `admit_extension`, `package.run` and `pending_call` forbidden, resume count 1 and `diagnosis_state` cleared.
  - Return and cap: each finding comes from changing the authored scientific dependency, then two `start_child` `InvalidInfra` failures (counter checked back at 0), then `stress_validation_exhausted`, a real factory-bug diagnosis, `factory_bug_held` and its replay, a new runtime revision, and a cross-batch resume with `build` and `validate_and_repair` forbidden.
  - The three admissions complete G8, G9 and G6 with counts 1–3, and the fourth retires. Extension-1 entry and outcome snapshot bytes are unchanged throughout. Nothing is seeded and the cap is not lowered.
- **Extension cap.** Five real diagnosis and admission cycles reach frontiers G16, G8, G9, G6 and G13. Each asserts the extension ID and `progress`, then `retire('retired_extension_limit')` with the writer and Evaluator forbidden.
- **Other branches.**
  - Partial and capture recovery: one-shot post-rename sync failure, G1 executed once, entry frontier G5 `unreached`.
  - Unchanged and irrelevant-edit writers retire with no progress.
  - G1, G5 and saved-cheat rejected writers: run_gates forbidden, the exact G1 diagnostic asserted, all outcome stages `unreached`.
  - Public match: real `loop_freshness` over the hash-checked HTTP fixture, `public_match`, gates `{'G2':'fail'}`.
  - Blocking and request-only stress use the real `stress_categories`.
  - Not-converging and malformed diagnosis: more than one call, covering the repair attempt.
  - Disabled policy: the card policy and the `DIAGNOSIS_ENABLED` env var grant nothing; result is `diagnosis_pending` with zero calls.
  - Deadline: `retired_batch_bound` is raised twice at `install`, with dispatch and writer forbidden.
  - Missing and corrupt proof, and interrupted freshness, stay at `extension_comparison_pending` with no history file.
  - The retired-label set must equal exactly the seven current-schema labels.
- **Runner compatibility.** The upstream `tests/run.py` has no per-script timeout and ran the new file as one script. I didn't redesign it.
- **Focused re-run on this host.** `AllOutcomesTests().branch()` passed for `ordinary-factory-bug` (7.9 s), `deadline` (4.2 s, `{'retired_batch_bound'}`), `not-converging` (3.9 s, `{'retired_not_converging'}`) and `interrupted-freshness` (2.0 s). The worktree was still clean afterwards.
- **Claims.** No Murphy row closes. The report says this is not VM, archive, Linux or live qualification, keeps `new-stream-d-current-comparison-1` open for the founder's pilot, and excludes the retired and pre-schema adapters.

This review was read-only: no edits, merges, pushes, network or model calls, subagents, or full suite.

## Writer disposition

PASS, with no blocking findings. O1–O6 are optional and are recorded for the
handback; no code or test changes were made after the passing review. The report
clarifies O2's authored `money_wait` trigger.
