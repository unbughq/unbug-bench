## Goldfish diff review, round 1: `ff31d87..a8c5e32` (t3/stream-d-implementation)

Mode: REVIEW, read only. Personas: zoom_out and implementation_readiness. Standard: implementation-readiness-standard. Reviewed against `docs/designs/stream-d-batch-diagnosis-opt-in.md` and the binding dispositions in `docs/reviews/stream-d-batch-diagnosis-opt-in-design-1.md`.

## Verdict

- **Code (this increment): PASS. No blocking findings.**
- **Delivery (landing on `factory-simplify`): NOT PASS as a plain merge.** One Blocker for the merge step (I1 below). It is not a defect in this branch's code. The merge must include a small mechanical test migration and a locked suite run on the merged tree.

## Checks against the design

**Global switch removed.**
- `batch_service.DIAGNOSIS_ENABLED` is deleted.
- All four production readers have moved: `batch_service.py:337`, `diagnosis_dispatch.py:233/242/255` (one evaluation reused for both branches, as M3 required), `diagnosis_dispatch.py:350`, and `extension_package.py:558-565`.
- `docs/practice/b3/preflight.py` now checks `batch_money.diagnosis_enabled(manifest)` (M1).
- On this branch, `grep DIAGNOSIS_ENABLED factory tests tools bin docs/practice` finds only `test_job_config.py:93`. That line is a deliberate environment-variable spoof, which is correct.

**Policy shape and default off.**
- `batch_money.diagnosis_enabled` returns False when the field is absent. Otherwise it requires exactly the keys `{schema, enabled}`, with `type(schema) is int` and `== 1`, and `type(enabled) is bool`.
- Anything else raises `MoneyWait('money_wait')`. `check_manifest` calls it, which follows the `replacement_policy` pattern.
- `test_batch_money` covers absent, true and false, all ten malformed shapes, and a policy-only file edit being refused by `money.manifest`.
- No tracked manifest opts in: `factory/batches/*` and `factory/practice.py` contain no `diagnosis_policy`.

**Authentication boundary.**
- `job_config.diagnosis_enabled` reads only `c.authenticated_batch_manifest`. Only `install` writes it (`job_config.py:167`), and only after `verified_config`.
- `install` resets it to None at entry (`:99`, N3).
- Cards, `checkpoint_card` and the environment are ignored, and `test_policy_comes_only_from_current_verified_manifest` proves it.
- The same test shows hash drift refuses install, clears the installed policy and returns False.
- `test_two_independent_batch_installations_do_not_share_activation` runs two real deliver/verify/install paths with independently pinned manifests. This is the design's midterm exam.

**Current authority.**
- The enabled path calls the real `for_case`, then requires the manifest's (id, deadline) to equal the authority's (batch, batch_deadline).
- `BudgetError` is a subclass of `RuntimeError`, so it is not caught by the `(MoneyWait, KeyError, TypeError, ValueError)` handler. `retired_batch_bound` therefore propagates unrenamed.
- `test_enabled_policy_rechecks_current_authority_and_shape` covers a wrong id, wrong deadline, malformed policy, missing binding, mismatched channel, and an expired deadline (which raises `retired_batch_bound`).

**Disabled replay semantics.**
- The gates replace the old global checks one for one. No early return was added before evidence validation.
- When disabled, `apply` still reaches the `extension_comparison_pending` stop, and `_dispatch` still stops with `diagnosis_pending` after its completed/malformed checks, exactly as before.

**Post-decision deadline (M3 disposition).**
- `test_stream_d_dispatch.py::test_deadline_after_durable_decision_replays_without_a_second_call` expires the deadline just after `decision()` returns.
- It asserts `retired_batch_bound`, one model call, and then a replay that returns 0. The replay leaves `decision.json` bytes, the call count and the ledger bytes unchanged, and `run.opencode` is patched to fail if called.

**Cheap observation guards (M2).**
- The policy is now the last term in `observation_enabled`.
- `test_stream_d_entry.py::test_expired_enabled_policy_refuses_before_observation_or_gate_work` drives the real `run.run_gates`. `_gate_pipeline` is patched to return `self.pipeline` (entry `:49`), so `invoke.assert_not_called()` is a real check. The test also shows `rehearse_only` short-circuits before authority is touched.

**Host accounting isolation.**
- `batch_money.diagnosis_enabled` imports nothing.
- `job_config.diagnosis_enabled` imports `budget`/`job_authority` lazily, only on the worker path.
- The suite log shows `test_host_job_config_does_not_load_worker_accounting` still passing.

**Real installer versus authored controls.**
- The real install proof is in `test_job_config`. Its release and manifest envelopes are authored, but the hash and install checks are real, and the docstring says so.
- `runtime.diagnosis_policy`, the RuntimeTests minimal `{id, batch_deadline}` manifest, and the subprocess `authored-control.json` (which now serializes `authenticated_batch_manifest` and selects policy per fault, N4) are all labelled as controls.
- `test_batch_service_d` uses independently pinned enabled and disabled fixtures (`freeze()` before collection). It copies a real D projection into the disabled journal as a labelled stored-state control, and patches `_project` to fail if called.
- `test_batch_admission_clamps` is migrated (N1).
- No fixture is generated by the code under test, and no row-closure claim depends on one.

**Docs (M4).** The item-8 rollback paragraph (`stream-d-item8-offline-preparation.md:441-445`) now says: default off when absent or false, the journal is pinned to the manifest SHA and never edited in place, and rollback means stopping B admissions plus a separately reviewed default-off batch or release.

**Suite evidence.**
- `...T111704Z-83f1739e.json` records: plain `lockf` command, timeout 7200000, head `cf3415a`, production `d7250f9`, exit 0, 180 scripts, 0 failed. The log tail agrees.
- `git diff --stat d7250f9..cf3415a -- factory` is empty.
- `cf3415a..a8c5e32` touches only docs and reports.
- The DNS, cancelled and exit-75 records are labelled as non-results, which is correct.

**Murphy.** No row is claimed closed, which is correct: row 9 needs the production queue-to-diagnosis cycle from increments 2 and 3.

**Zoom-out.** Net production change is +42/−14 lines. No new module, schema, environment flag or authentication path. A global was deleted in favour of an already-authenticated record. No YAGNI concerns.

## Findings

### Blocker for the merge step (not for this increment's code)

**I1. `factory-simplify` adds four test contexts that patch the removed symbol.**

Evidence, from `git show factory-simplify:<path>`:
- `tests/factory/test_stream_d_blocking_stress.py:278`: `patch.object(batch_service, 'DIAGNOSIS_ENABLED', True)` around `diagnosis_dispatch.apply(..., resume=True)`
- `tests/factory/test_stream_d_blocking_stress.py:311`: `patch.object(service, 'DIAGNOSIS_ENABLED', True)` around `service.plan(...)`, inside `check_batch_retirement`, using a `ServiceTests` fixture
- `tests/factory/test_stream_d_writer_rejection.py:172` and `:184`: the same patch around `diagnosis_dispatch.apply(...)` with `resume=True` and with `comparison_route=True`

Why it blocks the merge:
- `merge-tree` is textually clean (merge base `ff31d87`), but `unittest.mock.patch.object` raises AttributeError when the target attribute does not exist and `create=True` is not passed.
- After the merge, these tests error out. The merged `factory-simplify` would fail the required full suite.
- The 180/0 pass was measured at `cf3415a` on the `ff31d87` base, so it does not cover the merged tree.

The migration is mechanical and already supported by both files:
- Both files already `import test_stream_d_runtime as runtime`.
- Their `self.c` comes from the RuntimeTests, ExecutionTests and EarlyWriterTests setups, which carry `authenticated_batch_manifest` after this branch.
- **Lines 278, 172 and 184:** replace the patch with `runtime.diagnosis_policy(self.c)`.
- **Line 311:** after the merge, the `ServiceTests` record already defaults to `diagnosis_policy={schema:1, enabled:True}` and is frozen in `setUp`. Drop the patch and leave `service.plan(...)` as it is.
- Remove any `import batch_service` lines left unused.

Required for merge:
1. Do this migration in the merge commit, or in a pre-merge commit on top of `factory-simplify` content.
2. Re-grep `DIAGNOSIS_ENABLED` across `factory tests tools bin docs/practice` on the merged tree. Expect only the `test_job_config.py:93` environment spoof.
3. Run one locked full suite on the merged tree before landing.

This is a delivery gate, not a code fix to this increment. It should not be hidden behind "dry-merges cleanly".

### Nits

- **N-a.** `job_config.install`'s early return (no `batch_release_sha256`) leaves any previous `authenticated_batch_manifest` in place. This is harmless today because `c` is per-process and non-batch runs never set it. One line would make the reset unconditional, but it is not required.
- **N-b.** `job_config.diagnosis_enabled` catches TypeError and ValueError around `for_case`. Today `for_case` raises only BudgetError, so nothing is masked. If `for_case` ever raises plain TypeError or ValueError for a different reason, it will silently become `money_wait`. That fails closed, so it is acceptable.
- **N-c.** The `apply` gate runs after the in-memory card update to `stopped`/`terminal_stop`. This is intended under the M3 disposition and covered by the replay regression above. I note it only so a future reader does not "fix" the ordering.

## Skipped checks

- No suite, test files or live calls were run, as instructed. I did not re-run `merge-tree` beyond confirming the merge base and that it does not fail.
- I did not run the four `factory-simplify` tests against the branch. The AttributeError conclusion comes from `mock.patch.object` semantics plus the grep, not from execution.
- I did not audit `factory-simplify`'s other production changes (`extension_package.py` +66, `extension_writer_rejection.py`, `budget.py`) for semantic interaction with the new `observation_enabled` ordering. A grep shows no new production `DIAGNOSIS_ENABLED` reader there. The merged-tree suite is the check for the rest.
- I read the design docs only for the sections cited, and did not review increments 2 and 3, B's pilot admission, or E's O5b content.

## Residual risks

- This increment gives no production diagnosis cycle. Collection to plan, and resume draining, are increments 2 and 3. Opting a batch in today only enables the worker gates and an otherwise uncalled `plan` path.
- Most stream-D control-flow suites prove behaviour under an authored installed policy, not under a real installation. Authorization proof rests on `test_job_config` and `test_batch_money` alone, as the design intends.
- Once a pilot manifest opts in, a deadline passing mid-run will surface as `retired_batch_bound` from `run_gates` and `apply`. That is intended, but it is a new place where a real batch can stop.

## Elephant disposition

Implementation PASS accepted. Merge blocker I1 accepted in full: rebase this branch onto factory-simplify 7dbdc58, migrate all four new test contexts to the manifest-policy controls, re-grep all executable references, run the locked full suite on the combined tree, then obtain a fresh round-2 diff review. This is a real semantic integration conflict despite the clean textual merge; no blocker is rejected or self-verified. N-a/N-b/N-c are deferred as optional nits; no production change is needed for them. No Murphy row closes.
