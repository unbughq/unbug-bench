**Goldfish design review, round 1: `docs/designs/stream-d-batch-diagnosis-opt-in.md` @ cb39a1d**

Mode: REVIEW, read only. Personas: zoom_out, design_critic, implementation_readiness. Standards: Heilmeier and implementation-readiness.

## Verdict: PASS. No blockers.

The four Majors below should be fixed in the design or handled in the implementation. None of them can enable diagnosis on a batch that has not opted in, and none can spend money.

## What I checked against the code

- **Reusing the existing manifest is enough. No new config schema is needed.**
  - Host side: `batch_service.plan` already gets its record from `batch_money.manifest(policy, root)` (`factory/batch_service.py:333`). That call checks the release, the manifest path, the manifest hash and the source-manifest pin (`factory/batch_money.py:83-105`).
  - Worker side: `job_config.install` stores `authenticated_batch_manifest` only after `verified_config` passes (`factory/job_config.py:85,148`). `verified_config` checks the hash in the worker-release manifest and that the record's id and deadline match the config (`factory/job_config.py:52-62`).
  - `factory/diagnosis.py:416` already reads `c.authenticated_batch_manifest`, so this is an existing consumer being reused.
  - The proposed `diagnosis_policy` follows the existing `replacement_policy` pattern exactly (`factory/batch_money.py:46-50`).
  - `check_manifest` does not reject unknown top-level keys today. Validating the new field there is therefore the right fix, not a widening.
- **Production gates.** All four production uses in `factory/` are listed correctly:
  - `factory/batch_service.py:341`
  - `factory/diagnosis_dispatch.py:242`, `:255` and `:350`
  - `factory/extension_package.py:561`, reached through `factory/run.py:3050-3051`

  One non-test executable reference is missing; see M1.
- **Default off.** A batch with no `diagnosis_policy` returns False before any authority lookup. Neither tracked manifest (`factory/batches/b-plumbing-practice-2.json`, `factory/batches/b-practice-20261031.json`) contains the field, and `factory/practice.py:11-20` (the EXPECTED manifest) does not either. Non-batch runs never reach install (`factory/run.py:3349`), so they have no installed manifest and the answer is False.
- **Cross-batch and current authority.**
  - Install always uses the current launch manifest.
  - Predecessor manifests are still validated through `check_manifest(old, _ancestors=False)` (`factory/batch_transfer.py:56-60`). A predecessor with a malformed policy now refuses, which is correct, and its opt-in is never carried over.
  - The id/deadline match against `for_case` repeats install's own check (`factory/job_config.py:59`). It is cheap and keeps the current-authority binding visible, so keep it.
- **Founder decision.** This matches the 2026-11-03 paragraph in `docs/designs/stream-d-item8-offline-preparation.md:20-24` ("pinned authenticated batch opt-in", no global flip) and B's Diagnosis-scheduling row in `abc11ef:docs/designs/pilot-run.md:19` ("toggling the constant alone is insufficient"). Pilot admission and Boat settlement stay with B.
- **Heilmeier.** Every section is present, if terse: objective, current state, new approach, payoff, risk, cost ($0), timeline (one cycle), midterm and final exams. Murphy row closures are honestly listed as none.
- **Zoom-out.** No new module, schema, environment flag or second auth path. The helper sits in `batch_money`, which both host and worker already import (`factory/job_config.py:13`). This is a deletion-first change and passes.

## Findings

### Major

**M1. One executable reference to `DIAGNOSIS_ENABLED` is not listed.** Scope: design lines 45-47; `docs/practice/b3/preflight.py:52`.
- `require(not batch_holder.HOLDER_ENABLED and not batch_service.DIAGNOSIS_ENABLED, …)` will raise AttributeError once the constant is deleted.
- The file says it is a "historical frozen preflight" and no test runs it, so it fails closed. It is still a choice left to the implementer: edit a frozen artifact, or leave it broken.
- **Fix:** state the choice. Either drop the `DIAGNOSIS_ENABLED` half of that check, or record that the historical preflight is knowingly broken.

**M2. The design does not say how `observation_enabled` may fail.** Scope: design lines 89-91; `factory/extension_package.py:558-563`; `factory/run.py:3050-3051`.
- `observation_enabled` runs on every `run_gates` call for factory jobs.
- With the policy on, `job_config.diagnosis_enabled` calls `for_case`, and `for_case` can raise `money_wait` or `retired_batch_bound`. That includes a deadline passing mid-run (`factory/job_authority.py:46-47`).
- A predicate that could only return a bool now raises inside the ordinary gate pipeline, before the pipeline's own budget boundary runs. The design does not say whether raising is intended there, or what order the checks run in.
- **Fix:** specify the order. Run the cheap existing guards first (`factory_job`, dry_run, rehearse_only, audit_fairness, late_gate_rehearsal, audit_source, audit_gates), then the policy. State that a BudgetError from an enabled policy propagates out of `run_gates`.
- Add one test: enabled policy plus expired authority makes `run_gates` refuse before calling `observe` or `pipeline.run`.

**M3. The predicate is re-evaluated at each gate inside one dispatch.** Scope: design line 89 versus `factory/diagnosis_dispatch.py:224-260,306-354`.
- `_dispatch` already calls `job_authority.for_case(c)` at line 311.
- The design then re-runs a time-dependent `for_case` at `apply` (lines 242 and 255) and at line 350. `apply` changes the card in memory (lines 230-231) before the line-255 gate.
- If the deadline passes between line 311 and line 255, `apply` now raises after that mutation instead of reaching `retain_extension_resume` and the scorecard write. `decision.json` is already saved, so no completed result is lost. It is still a new failure point that the design says it does not add (lines 104-107), and it makes three redundant authority reads.
- **Fix (simpler):** evaluate `diagnosis_enabled(c)` once at `_dispatch` entry, next to the existing `for_case`, and carry the bool to `apply`. Or keep per-gate calls and state explicitly that refusing after a durable decision is intended, with a test proving that replay after the refusal is unchanged.

**M4. The governing founder doc becomes stale.** Scope: `docs/designs/stream-d-item8-offline-preparation.md:434-439`.
- That paragraph still says "Normal DIAGNOSIS_ENABLED stays False … Rollback pins False".
- After this change the constant no longer exists. Rollback becomes "release a manifest without `diagnosis_policy`, or stop admissions through B".
- Also note that `_load` pins the journal to the manifest SHA, so a running batch cannot be flipped mid-flight.
- **Fix:** update that paragraph in the same commit so the governing doc and the code agree.

### Nit

- **N1. Test list.** Design lines 127-139 name `test_batch_money`, `test_job_config`, `test_batch_service` and "existing stream-D tests". `tests/factory/test_batch_admission_clamps.py:116` also patches `service.DIAGNOSIS_ENABLED` and needs its practice fixture frozen with the policy. Name it so the migration list is complete. The other seven patching files are `test_stream_d_*` or `test_batch_service` and are covered.
- **N2. Inaccurate claim at line 68.** "Before any D import" is not quite true: `retire_legacy` already imports `diagnosis` before the gate (`factory/batch_service.py:307-308`). The behaviour does not change; only the wording is off. Say "before projection and enqueue".
- **N3. Reset the manifest on install.** Lines 85-87 rely on a failed install emptying `authenticated_job_config`, so that `for_case` raises `money_wait`. In that state `diagnosis_enabled` raises rather than returning False. It does fail closed. Still, resetting `c.authenticated_batch_manifest = None` next to `factory/job_config.py:80-81` is one line, and it makes "missing installed manifest means False" literally true after a failed reinstall.
- **N4. Subprocess harness.** The control serialization at `tests/factory/test_stream_d_dispatch.py:181` must add `authenticated_batch_manifest`, and the child-script toggles at lines 208 and 253 must become per-fault policy. Line 137 of the design implies this; one explicit sentence would remove the guesswork.

## Skipped checks
- I ran no tests, suite, live calls or delegation, as instructed.
- I did not review the outlines for increments 2 and 3 as deliverables.
- I did not audit B's admission or settlement design beyond its Diagnosis-scheduling row.
- I did not read every `test_stream_d_*` fixture to confirm it can carry an authored installed manifest. I checked only `test_stream_d_held`, `test_stream_d_resume_target`, `test_stream_d_entry` and `test_stream_d_dispatch`, plus the host fixtures in `test_batch_service` and `test_batch_admission_clamps`.
- I did not verify that `key_holder.fingerprint` or other trusted-code pins elsewhere need refreshing. Any code change moves them, so this is not specific to this design.

## Elephant disposition

PASS accepted. M1: update the historical preflight to test its pinned manifest policy rather than a deleted global. M2: cheap observation guards run first; enabled-policy BudgetError propagates before observe/pipeline.run, with a regression. M3: retain current-authority checks at separate execution boundaries; apply evaluates the policy once for both local branches. Deadline refusal after a durable decision is intentional, and replay must consume that same decision without a new call. M4: update rollback language and state that a pinned running journal cannot be toggled in place. N1–N4 accepted: migrate the admission-clamp fixture, fix projection wording, reset the installed manifest on install, and serialize the subprocess policy explicitly.
