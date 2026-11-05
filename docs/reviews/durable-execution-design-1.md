# durable-execution design review 1

Reviewer: fresh goldfish subagent (general-purpose), read-only, personas zoom_out,
design_critic, implementation_readiness, Mode: REVIEW. Reviewed commit 9513a29.
Verbatim below; the resolution follows at the end.

---

# Goldfish design review: `docs/designs/durable-execution.md` (branch `durable-execution`, 9513a29)

Personas: zoom_out, design_critic, implementation_readiness. Mode: REVIEW. Standards: heilmeier-standard.md and implementation-readiness-standard.md.

Tests run:
- `tests/factory/test_durable_contract.py`: 13 tests, OK.
- `tests/factory/test_durable_replay.py`: **FAILED in 3 of 3 runs.** `test_crash_during_provider_sleep_keeps_the_deadline` fails with `DBOSUnexpectedStepError: ... step 6, function DBOS.sleep was recorded when attempt was expected`. `test_crash_mid_step_reruns_only_open_step` passes.

---

## BLOCKING

### 1. The replay test that "proves" the engine fails, and its sleep pattern will permanently wedge cases in production
- **Evidence.**
  - `tests/factory/test_durable_replay.py:60`: the workflow body runs `DBOS.sleep(max(0.0, r.retry_at - time.time()))`. That reads the clock inside the workflow, which breaks the design's own engine rule 1 (design :83).
  - In dbos 3.4.0, `DBOS.sleep` returns early when `seconds <= 0` and records nothing (`dbos/_dbos.py:2095`).
  - On replay after the wake time has already passed, the sleep is skipped. The next `attempt` call then takes function_id 6, where the journal holds `DBOS.sleep`, and the workflow errors permanently.
- **Reproduction.** I instrumented a copy of the program. The second process computed `dur -0.64`, so the wake time had passed before replay reached the sleep. Changing the floor to `max(0.001, …)` made the case finish correctly (op 6 = DBOS.sleep, op 7 = attempt).
- **Production impact.** Any control-VM outage longer than the remaining provider wait turns the case into a terminally errored workflow. A reboot during a short limit is enough. The design (:44-46, :149-152) cites this test as the proof, and WP1 will copy its pattern.
- **Fix.**
  - Add an engine rule: every durable wait calls `DBOS.sleep` with a strictly positive duration, for example `max(0.001, retry_at - now)`, so the sleep op is always recorded. Better, get `now` from a step.
  - Fix the test, and add a case that restarts the process after `retry_at` has passed.
  - Do not cite the test as proof until it passes under the full suite's load.

### 2. Engine rule 4 (a new `application_version` per code change) orphans every in-flight case on every deploy
- **Evidence.** DBOS recovery selects pending workflows with `application_version == GlobalParams.app_version` (`dbos/_sys_db.py:3218`; `_dbos.py:899`). An engine started with a new version never recovers the old version's pending cases. Design :91-92 says fixes "apply at the next step boundary". Under this rule they never apply, and the cases hang.
- **Second problem.** `StepInput.code_version` (contract :135) and `BatchSpec.release_digest` (:199) are one digest that has to mean two things: the bench version the case pins and the plumbing version that should roll forward (ENGINEERING §3, §4).
- **Fix.**
  - Pin one `application_version` for the life of the engine database (or per batch). Plumbing changes then live in step code, which is not replay-checked. Workflow-body changes go behind `DBOS.patch()`.
  - Alternatively, specify migration by `DBOS.fork_workflow`. That creates new workflow IDs, so it has to be reconciled with rule 2 and with workflow ID = case_id.
  - Split `code_version` into `bench_version` (pinned per case, per gate) and `plumbing_version`.
  - Add a replay test: start under version A, crash, restart with changed step code, and assert the case resumes.

### 3. The idempotency key collides after a repair, so a worker can return a stale gate result
- **Evidence.** `contract.py:155`: the key is `case_id/step.name/attempt`. Gate steps are forced to `round=0` (:92), so the name is just `gate:G1`.
  - After a REPAIR, the case reruns the gates. `run.py` `validate_and_repair` clears `gates` and reruns them all.
  - The second pass's `gate:G1` attempt 1 then has the same key as the first pass. Under rule 3 (design :88-90) the worker returns the pre-repair result.
  - The same collision happens on factory-bug resumes and extensions.
- **Fix.** Put a monotonic per-case step sequence number into the key and into `StepInput`, or the input snapshot's sha. Add a contract test that two gate inputs with different snapshots get different keys.

### 4. `decide()` does not implement ENGINEERING §3: no diagnosis, no extensions, and no factory-bug resume limit
- **Evidence.**
  - `EXHAUSTED → RETIRE` (contract :293-294), and a repairable `GATE_FAILED` at the round cap also goes to `RETIRE` (:290-292). §3 says a case that runs out of rounds or budget goes to the diagnosis agent, which picks factory bug, close to passing or not converging.
  - `DIAGNOSE` happens only when infra retries run out (:288, :272).
  - `BatchSpec.max_factory_bug_resumes` (:208) is never read.
  - There is no extension count (at most 5), no progress check, no diagnosis step kind, and no verdict type. Stream D defines `factory_bug|close_to_passing|not_converging` (`docs/designs/stream-d.md:334`).
- **Ownership gap.** `factory/diagnosis.py` (875 lines), `diagnosis_dispatch.py` (490), `extensions.py` (527) and `extension_package.py` (838) appear in no package and not in the deletion list. Yet `run.py` imports them about 37 times.
- **Murphy impact.** Row 9 would "close" by retiring cases without diagnosis.
- **Fix.**
  - Add `StepKind.DIAGNOSIS`, a `Verdict` enum and Actions `EXTEND` and `RESUME_AFTER_FIX`.
  - Pass `extensions_used`, `factory_bug_resumes` and a progress flag into `decide()`, and enforce 5, 3 and progress in code.
  - Route EXHAUSTED and round-cap failures to DIAGNOSE plus a replacement.
  - Name the package that owns diagnosis and extensions, and say what happens to those four modules.
  - Do this before freezing, because every engine and worker package depends on it.

### 5. The contract is missing seams the packages need to build "against contract.py alone"
- **(a) WP2 and WP5a wire protocol, owned by neither.** Undefined:
  - what command `remote.py` runs over `boat ssh`, and how the `StepInput` and case key are delivered;
  - that the worker-side attempt is detached from the ssh session (setsid or systemd-run), without which a control-VM crash or deploy SIGHUPs a multi-hour writer round and rule 3 is moot;
  - where a key's result is stored for reattach;
  - the per-step wall deadline. Today there are 74 stalls and 23 timeouts; DBOS steps have no timeout, so a hung ssh hangs the case forever.
- **(b) Ledger protocol for WP1 and WP6.** "Checked before every paid step" (:114) has no API. `StepInput` has no money ceiling, so the worker cannot stop mid-step. A check before the step overshoots the bound by up to `max_concurrency` × one step's cost ($15.05 per round, ENGINEERING :127).
- **(c) WorkerPool protocol for WP1 and WP2.** Acquire and release are undefined, including whether a worker is released during a provider sleep. "Hold no worker" (:51) contradicts "a case keeps its worker" (:56).
- **(d) Key delivery for WP7 and WP2/WP5a.** "Over the ssh channel into RAM" (:115) is in neither package's interface.
- **(e) `ArtifactStore.put(data, kind)` has no case or recipient scoping** (:247-251). With per-case age keys, WP3 and WP7 will each invent one.
- **Fix.** Add `WorkerChannel`/`RemoteAttempt`, `Ledger` (reserve, record, release) and `WorkerPool` protocols. Add `deadline_s` and `money_ceiling_usd_micros` to `StepInput`. Add `case_id` to `ArtifactStore`. Freeze all of it now.

### 6. A linear chain of coarse steps cannot express today's gate pipeline, and it throws away expensive work
- **(a) G10 overlap is lost.** G10 runs concurrently from G6 and is joined before G11 (`factory/gate_pipeline.py:189-205`). One gate per sequential step, with G10 grouped with G17 and G11 in WP5e, loses that overlap: hours of calibrator wall time per pass. The contract's single `snapshot` per result cannot merge two concurrent steps.
- **(b) Early-gate reuse is lost.**
  - G3, G4, G5 and G15 (`early_checks`) and G8 and G9 (`early_review`) run inside the writer loop. The gate loop reuses them only through the in-memory `c.early` (gate_pipeline :147-151), which is gone once each GATE step builds a fresh runner context.
  - G3 is not in `gate_state.REUSABLE` (`gate_state.py:14`), so it reruns (about 20 minutes).
  - G8 and G9 reuse depends on whether gate_state files are inside the snapshot.
- **(c) Snapshot scope is undefined.** "Case tree" (`ArtifactKind.CASE_SNAPSHOT`) could mean `c.case` or `c.work`. In-round recovery state (`attack-state.json`, `prototype.json`, `infra-attempts.json`, gate caches) lives in `c.work`, so the claim that "in-round recovery keeps working inside a step" (:97) holds only on the same live worker.
- **(d) Step order after REPAIR and the STRESS outcome are undefined.** Which gates rerun after a repair? What does a STRESS round that finds a problem return, given that `feedback` is allowed only on GATE_FAILED (:181-185)?
- **Fix.**
  - Decide G10 explicitly: either a child workflow or async step joined before G11 with a stated snapshot rule, or an accepted serial cost written into the design.
  - Define CASE_SNAPSHOT as the `c.work` subset to retain.
  - Record early-gate results as receipts that later GATE steps consume.
  - Write the step sequence, including after REPAIR and for STRESS outcomes, into the design so WP1 has nothing to choose.

### 7. Admission needs cross-case state that no package owns
- **Evidence.**
  - ADMIT dedups against the other cases' statements through the shared statements registry and selection board: `run.py:783-830` (`selection_statements`, `prior_statements`, the `STATEMENTS_KEY`, registry reservations), `admission.py` and `registry.py`.
  - `StepInput` carries no batch selection context.
  - Nothing serializes concurrent admissions. With `max_concurrency > 1` and immediate replacements, two cases can choose the same bug.
  - Neither module is in a package or the deletion list.
- **Fix.** Run ADMIT as a serialized batch-workflow step (or a DBOS queue with concurrency 1). Give `StepInput` a registry `Ref` of the new kind `STATEMENT_REGISTRY`, and assign the registry to a package.

### 8. Secrecy holes in what the engine records and publishes
- **(a) Reason codes can carry content.**
  - `CODE` (:21) allows 80 characters of `[a-z0-9_.:/-]`. That fits file paths and identifiers such as `g5:src/modules/inventory/reserve.ts`.
  - The public scorecard is generated from these tables (design :64-65), so a reason code that names the bug's file reaches contestants.
  - Fix: freeze an allowlist (an enum of `<stage>:<code>`) in the contract.
- **(b) Exceptions bypass the contract.**
  - DBOS pickles a step's exception into `operation_outputs.error` and the workflow status, and `dbos_logger` logs it.
  - `CalledProcessError` and ssh stderr can carry case content.
  - Fix: add a rule and a test that executors never raise; everything becomes `INFRA_ERROR` with a code.
- **(c) `Ref.sha256` semantics are undecided.**
  - "Same bytes give the same Ref" (:111, :248) cannot be a ciphertext hash, because age encryption is randomized. So it is a plaintext sha256.
  - Plaintext hashes in public cards allow confirmation of guessed small artifacts (answer keys, one-line patches) and show equality across cases.
  - Fix: specify HMAC-SHA256 under the case key, or ciphertext sha with no dedup guarantee.
- **(d) Conductor can still turn on.** It starts from env alone (`DBOS__CONDUCTOR_KEY` / `DBOS__CONDUCTOR_URL`, `_dbos.py:955-972`). Assert at startup that these are absent and `conductor_key` is unset.

### 9. Murphy row targets are not honest for the packages they are assigned to
- **Row 35** ("hours of active work have no off-worker checkpoint") is assigned to WP3. With coarse steps, a writer round or G10 still has no off-worker boundary until WP5f, so move it to WP5f.
- **Rows 2 and 47** need a batch-wide account scheduler and shared account health (register fix column). WP4 is "failure classification only" (:112).
- **Row 9** conflicts with §3 (finding 4).
- **Rows omitted** even though their code is deleted or affected: `new-batch-service-3` (batch_service is deleted), `new-stream-d-outcome-routes-1`, `new-stream-d-current-comparison-1`, `new-ancestor-release-binding-1`, `new-predispatch-import-recovery-1`, `new-worker-router-delivery-1` (WP2/WP7 delivery).
- **Fix.** Reassign or drop these targets and list the omitted rows, so each package's "Done when" is provable by that package.

### 10. Write ownership overlaps, so wave 1 is not disjoint as claimed (:104-105)
- `factory/run.py` is written by WP5a ("minimal hooks", undefined), then WP5b–e (G10 overlap and early reuse need runner hooks), then WP9. WP9 must remove `run.py` imports of deleted modules: late_recovery 10 references, restart 5, founder_ruling 4 (including the first line of `write_and_attack`), durable_checkpoint 4, recovery 3, late_rehearsal 3. Yet WP9 owns only "the deletion list". The daily `factory-simplify` merges (:125) also touch `run.py`.
- Failure classification is written twice: WP4 "maps every stop kind to one Outcome" and WP5a "classify into a StepResult".
- `model_runtime.py` is owned by both WP4 and WP5f.
- **Fix.**
  - Make WP5a the sole `run.py` owner in waves 1–2, with a list of the hooks it adds.
  - Have WP4 deliver a pure `classify(stop) -> (Outcome, reason, retry_at)` that WP5a calls.
  - Add `run.py` to WP9's write set explicitly.

---

## NIT

11. **Heilmeier gaps.**
    - Missing: cost (Postgres, backups, control-VM sizing, engineering effort), timeline per wave, and mid-term and final exams beyond each package's "Done when".
    - The objectives use jargon ("journal", "replay", "push-to-worker").
    - The "about 460 interruptions" figure is not tied to a command that reproduces it.

12. **The deletion list is incomplete, and its size claim is high.**
    - The listed Python modules total about 5.9k lines; with `launch.sh` (808) and `resume-in-place.sh` (54) that is about 6.7k, not "about 10.6k".
    - Missing from the list: `restore-cases.sh`, `launch-slots.sh`, `collect.sh`, `bin/factory-adopt`, `bin/boat-launch-guards.sh`, `account_handoff.py`, `control/unbug-resume-launches.*`, `founder_decisions.py`, `job_config`/`job_authority`. It also does not say whether the statement-only and sealed-audit paths survive (`statements-round.sh`, `sealed_audit.py`, `g11_review.py`).
    - "The salvage path" has no module. In production it is `run.py:restore_gate_crash` (:951), which should be named.

13. **The branch flow deviates from ENGINEERING §1.** Packages branch from and merge into `durable-execution`, not `factory-simplify`, and Murphy row numbers are assigned only on `factory-simplify`. State this as an approved exception.

14. **`PROVIDER_LIMIT` is unbounded.**
    - A misclassified error with a near `retry_at` loops forever. Each attempt can still spend `Usage` before hitting the limit (the test asserts SLEEP at 10,000 attempts).
    - Fix: send N consecutive limits with spend and no progress to DIAGNOSE.
    - WP4 also needs a rule for a limit with no reset time, because the contract demands a finite `retry_at`.

15. **Two sources of truth for limits.**
    - `EXHAUSTED("rounds")` duplicates `GATE_FAILED` at the round cap.
    - It is unstated who emits EXHAUSTED for the batch money bound (the engine) versus case limits (the worker).
    - `spec.max_writer_rounds=6` sits beside the runner's `--rounds` (default 8, register row 9) and `ordinary_limit_usd`. Specify how the spec maps onto runner arguments.

16. **ESCALATE semantics are unspecified.** Does a parked case keep its concurrency slot? Does a replacement launch? Which steps may return `NEEDS_FOUNDER`?

17. **Record strictness.**
    - Nested extra keys raise `TypeError`, not `ValueError` (`Usage(**d)`, `Ref(**d)`, `Step(**d)`).
    - `StepInput.step`, the `feedback` Ref kind (should be WRITER_FEEDBACK) and the `snapshot` kind (should be CASE_SNAPSHOT) are not type-checked. `StepResult.receipt` and `diagnostic` kinds are not checked either.
    - `BatchSpec` and `SealedCase` have no `from_record`, although `BatchSpec` is a workflow input.

18. **Scorecard ownership is contradictory.** The SEAL step produces a `SCORECARD` Ref on the worker (contract :76), but the design says the public scorecard is generated from Postgres tables (:64). Pick one owner.

19. **Superseded doc.** `docs/factory-single-path.md` says "Do not first invent a second event engine". The design should state that it supersedes that doc.

20. **Zoom-out and reuse.** `gate_attempt.Outcome`, `factory_waste.attempt`, the `infra-attempts.json` journal and `gate_state` fingerprints already provide attempt classification and gate reuse. The design should say whether each becomes the step-internal layer or is replaced, so packages do not build a second copy.

---

## Verdict: FAIL

Ten blocking findings. The most urgent:
- the cited replay proof fails, and its pattern wedges cases (1);
- the versioning rule orphans cases on every deploy (2);
- idempotency keys collide after a repair (3);
- §3 diagnosis and extension policy is absent from `decide()` (4);
- key seams are missing from the frozen contract (5).

The contract should not be frozen, and wave 1 should not fan out, until 1–8 are fixed and 9–10 are re-scoped.

---

## Resolution (elephant)

The elephant checked findings 1 and 2 against the dbos 3.4.0 source before fixing
them. They hold: `DBOS.sleep` returns before recording when `seconds <= 0`
(`_dbos.py` `sleep`), and recovery filters pending workflows on
`application_version == app_version` (`_sys_db.py:3218`). No finding was rejected.
Contract version 1 becomes version 2, and the design becomes revision 2.

| # | Resolution |
|---|---|
| 1 | Fixed. Added `contract.wait_seconds` (always at least 1 ms) and engine rule 2. The replay test reads the clock through a `now()` step. Added a new test, `test_restart_after_the_wake_time_has_passed`. The 4 replay tests pass 3 runs in a row, and with 4 copies run at once. |
| 2 | Fixed. `application_version` is pinned (`factory-engine-1`), and workflow-body changes go behind `DBOS.patch()`. `code_version` is split into `plumbing_version` and `bench_version` (for a GATE step, that gate's own digest). Added a new test, `test_changed_step_code_resumes_under_the_pinned_version`. |
| 3 | Fixed. `StepInput.seq` is strictly increasing per case, and the key is `case/seq/step/attempt`. Added a new test, `test_keys_never_collide_across_repairs`. |
| 4 | Fixed. Added `StepKind.DIAGNOSIS`, the `Verdict` enum, Actions `EXTEND`, `RESUME_AFTER_FIX` and `DIAGNOSE`, and `decide_diagnosis()` enforcing 3, 5 and progress (`progressed()`). EXHAUSTED and round-cap failures go to DIAGNOSE. `STARTS_REPLACEMENT` covers DIAGNOSE, RETIRE and ESCALATE. New package WP10 owns diagnosis and extensions. |
| 5 | Fixed. Added the `WorkerChannel` protocol (detach, result under the key, start-if-absent, deadline), plus `WorkerPool`, `Ledger` (reserve and settle) and `KeyService`. `StepInput` gains `deadline_s` and `money_ceiling_usd_micros`. `ArtifactStore` is scoped. The design resolves the "hold no worker" contradiction with `release_worker_after_sleep_s`. |
| 6 | Fixed in the design and the contract. G10 runs as a child workflow started from G6 and joined before G17 (`CONCURRENT_FROM`). Gate steps never change the snapshot; WP5a's test enforces it. Early checks become explicit GATE steps, reused by the digest rule. `CASE_SNAPSHOT` is defined as `c.case` plus a retained `c.work` subset owned by WP5a. The step sequence, including REPAIR and the STRESS outcomes, is written out. |
| 7 | Fixed. ADMIT runs on a batch DBOS queue with concurrency 1 and gets a `STATEMENT_REGISTRY` Ref. New package WP11 owns admission and the registry. |
| 8 | Fixed. (a) Reasons use the `REASON` grammar (no paths, digits or dots), and WP4 ships the publication allowlist. (b) Added `guarded_run`, tested with an exception that carries content. (c) `Ref.digest` is HMAC-SHA256 under the scope key. (d) Added `assert_no_conductor`, tested. |
| 9 | Fixed. Row 35 moves to WP5f, row 9 to WP10. Rows 2 and 47 are declared outside this design. The omitted rows are added: `new-batch-service-3`, `new-ancestor-release-binding-1` and `new-predispatch-import-recovery-1` to WP9, the stream D rows to WP10, and `new-worker-router-delivery-1` to WP2 and WP7. |
| 10 | Fixed. WP5a is the only `run.py` writer in waves 1–2, with its hooks listed. WP4 delivers a pure `classify.py` and no longer writes `model_router` or `model_runtime`. WP5f owns `model_runtime`, in wave 4. WP9 owns `run.py` in wave 3. |
| 11 | Fixed. Added the goal, the mid-term and final exams, cost and timeline, and the reproduction method for the counts. Jargon is defined where it is first used. |
| 12 | Fixed. The list is corrected and completed, with about 6.4k lines replaced and 1.6k deleted. The salvage path is named (`run.py:restore_gate_crash`). Statement-only is replaced by ADMIT. The audit tools are kept. |
| 13 | Fixed. The exception is stated, with `new-durable-<n>` row names, and added as founder decision 5. |
| 14 | Fixed. `max_consecutive_limits` counts limit attempts that spent money, then DIAGNOSE. WP4 defines a backoff for a limit with no reset time. |
| 15 | Fixed. Only the worker emits EXHAUSTED, for its own ceiling or runner limits. The batch money bound is enforced by `Ledger.reserve`, not by a case outcome. The runner's `--rounds` is set from `spec.max_writer_rounds` (default 8, the runner default). |
| 16 | Fixed. ESCALATE parks the case, frees its slot and worker, and starts a replacement. Only the steps that run independent reviews may return it. |
| 17 | Fixed. Nested records are checked exactly and raise `ContractError`. Every `Ref` field checks its kind, `StepInput.step` is type-checked, and `batch_spec_from_record` is added. |
| 18 | Fixed. `SealedCase` holds only the archive; the control VM generates the scorecard from the tables. |
| 19 | Fixed. The design states that it supersedes `factory-single-path.md`. |
| 20 | Fixed. Today's in-step layers stay inside steps in waves 1–2. Reuse across steps moves to the engine. WP9 decides what goes. |
