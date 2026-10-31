The verdict is **PASS**: no blockers and no majors, with three optional nits. The fix narrows the finish block the way option (a) requires, and five of six mutations are caught by exactly the new test meant to catch them. The sixth mutant survives only because it changes nothing: `launch.sh` already runs under `set -eu`. I made no edits in the worktree. My `/tmp` copies are deleted, and the worktree is clean. The full review is below for you to save.

---

# Goldfish diff review 2: `stream-b-creation-intent`

**Reviewer:** fresh goldfish, read-only, no parent context. **Mode:** REVIEW. **Personas:** `zoom_out`, `implementation_readiness`. **Standards:** `implementation-readiness-standard.md`, `zoom-out-standard.md`.

**Tree:** worktree `t3-ded79ec5`, branch `t3/batch-service-control-vm`, diff `6f30f8d..HEAD`. There are three commits: `f30eb12` (the crash fix), `1e3463c` (narrows the settlement block) and `02ffd26` (the suite record). No code changes after `1e3463c`, so the suite record covers the code at HEAD.

**Read:**
- `docs/ENGINEERING.md`, the two persona files and both standards.
- The design, including its "Diff-review settlement clarification" section.
- Diff review 1 and the elephant's response to it.
- The full diff of `bin/boat-launch-guards.sh`, `factory/launch.sh` and the three test files.
- `guard_delete_receipt`, `guard_wait` and `batch_holder.record_child` / `_created`.
- The suite record and its log.

## Verdict: **PASS** (0 blockers, 0 majors, 3 nits)

## Review 1, Blocker 1: fixed as option (a)

**The code matches the design.**
- `guard_exit` now sets `guard_ids_failed=0`, then runs `guard_ids resolve || { guard_ids_failed=1; guard_cleanup_error; }`.
- `unfinished` starts from `guard_ids_failed`. The broad `[ "$guard_cleanup_failed" = false ] || unfinished=1` line is gone.
- So these failures still set `cleanup_failed` and a nonzero exit, but they no longer block `--finish`, which matches `6f30f8d`:
  - an orphan-list failure;
  - an orphan match;
  - a TTL-hook failure.
- Callers with no saved state:
  - They now keep `$state` when cleanup failed, and log "unfinished launch evidence retained".
  - The keep happens after `--finish` has already run, so it costs a temp directory, not a held reservation.
  - The design asks for this ("retain the temporary state if unfinished or cleanup failed").

**Mutation results.** I copied the tree at `1e3463c` to `/tmp` and ran `CreationIntentTests` there. All 9 tests pass. Then I applied six mutations:

| Mutation | Result |
|---|---|
| M1: `unfinished=0` (dropping the merge block) | Fails only `test_merge_failure_alone_blocks_finish_after_verified_retirement` |
| M2: restore the broad cleanup-failed block | Fails only `test_unrelated_inventory_error_keeps_prior_finish_semantics` |
| M3: a non-object JSON line is skipped (`continue`) instead of raising | Fails only `test_merge_failure_alone…` |
| M4: `launch.sh` changes `guard_ids persist \|\| exit 1` to `guard_ids persist` | Survives (equivalent mutant, see Nit 1) |
| M5: remove the "worker not owned by this launch" check in `guard_delete_receipt` | Fails only `test_merge_failure_keeps_prior_ids_and_reported_id` |
| M6: the pending scan uses `-e` only and drops `-L` | Fails only `test_dangling_marker_refuses_submission_and_finish` |

M3 can only fail the second half of its test: the first half's directory at `new.9` fails on `OSError` whether or not M3 is applied.

**The isolated test meets the review 1 requirement.**
- The worker is created through the real `guard_new` with status 0 (direct success).
- It is retired through the real `guard_retire` and the real receipt verifier, and `.deleted` exists.
- No pending marker is left, and `new.9` is a directory.
- Result: exit 1, `cleanup_failed: true`, no `finished_at`, no `complete`.
- M1 shows that only the merge block prevents finish here.

**Real ownership refusal.**
- The `guard_retire() { return 1; }` stub is gone.
- The test calls the real `guard_retire`, which refuses an ID missing from durable `ids`.
- It asserts "deletion receipt verification FAILED" and that no `delete` call was made.
- M5 shows that the ownership check is what refuses the deletion.

**Settlement still works when an unrelated step fails.** With `LIST_FAIL=1`, the run exits 1 with `cleanup_failed: true`, but `finished_at` and `complete` are both present. This matches the baseline.

**Test 1 now checks how resume ends, and holder receives the real exit code.**
- Each resume asserts `returncode == 0` and `cleanup-status == {primary_exit_code: 0, cleanup_failed: false}`, then `assert_unfinished`.
- `record_child` receives `resumed.returncode`.
- I read `batch_holder.record_child`: for `resume`, success means the `complete` file exists, and the exit code is ignored. So an exit 0 with no `complete` is still counted as a failure (`failures == 1`), as the design says.
- No new resume exit semantics are introduced.

## Other checks

- **Suite record.**
  - `head` is `1e3463c6…`.
  - `tree` is `c2cbe085…`, which equals `git rev-parse 1e3463c^{tree}`.
  - I recomputed the log's SHA256 (`97e288cc…8aad`) and it matches.
  - The log shows 158 scripts, 0 failed. `test_control_resume` ran 24 tests and passed.
  - Review 1, nit 8 is fixed.
- **Earlier crash-ordering properties are unchanged.** Intent is written with `O_EXCL` and fsync before the provider call. The `ids` merge is atomic and keeps every existing ID. The marker is unlinked only for a regular file. `id` is cleared on entry to `guard_new`.
- **Murphy register:** unchanged.
- **Claims:** no rows close, and there is no activation or cumulative USD 5 claim.
- **Review 1 nits:** placement (5) is fixed in the design text. Nits 1, 2, 3, 4, 6 and 8 are addressed. Nit 7 (fsync steps can't be tested) is honestly disclaimed.

## Zoom-out

- The fix is a net simplification: one flag replaces a broad condition.
- It adds no new paths, journals or switches.
- The tests reuse the existing harness, the saved `isolation-timeouts` artifacts and the real wrappers.
- Section 4 rules and security properties are unchanged.

## Nits (optional)

1. **`launch.sh:638` `|| exit 1` is redundant, so the propagation test doesn't depend on it.**
   - `launch.sh` runs under `set -eu` (line 476), and nothing turns it off before line 638. A failing `guard_ids persist` therefore already exits the script, and M4 is an equivalent mutant.
   - `test_resume_propagates_evidence_merge_failure_before_monitor` proves the real behavior: exit 1, the evidence message, no finish and no `complete`.
   - Its "no `ssh` call" assertion would not catch a resume that went on to monitoring with errexit off. In this fixture, `worker-owned` would not be probed before the merge failure exits either way.
   - Keep the explicit `|| exit 1` as documentation, or note that errexit is load-bearing here.
2. **`batch_holder._created` handles a non-object line differently.**
   - It calls `event.get(...)` on any parsed JSON, so a `42` line raises `AttributeError` instead of a deliberate evidence error.
   - `guard_ids` now rejects such a line on purpose.
   - This holder code is unchanged by this diff and the line fails closed through an exception. Align it when the holder is next touched.
3. **The design's wording is looser than the tests.**
   - "Direct success … covered" refers to status 0 through `guard_new` in the merge-alone and inventory tests. No test is named for it, so naming the test in the design would help.
   - "Unknown empty-ID resumes currently exit 0" is asserted for this fixture's route only, which is fine as worded.

## Money and scope

- The reserved hold is unchanged on every uncertain path: pending marker, merge failure and non-object evidence.
- Finish happens only after the real verifier sees a completed deletion, or, under unrelated cleanup errors, once every known worker is `.deleted` and nothing is pending (the baseline rule).
- Detached-provider and CLI-multiplicity residuals stay declared, and activation stays blocked.
- No Murphy rows close.

**To merge:** nothing blocking. The nits are optional.

## Elephant response and handoff

PASS accepted. All blocking findings were fixed and independently verified by this fresh reviewer. Keep the explicit resume error propagation as documentation. Optional holder non-object error alignment is deferred to the next holder change; no runtime code changed after tested commit 1e3463c6ecf799160108731dc57de7857bc32b6f. Direct status-0 success is covered by test_merge_failure_alone_blocks_finish_after_verified_retirement and test_unrelated_inventory_error_keeps_prior_finish_semantics. Unknown resume's exit-0 assertion describes the tested empty-ID fixture route.

Full suite: 158 scripts, 0 failed. The unique committed log/result is stream-b-creation-intent-suite-20261031T124233Z-70ff84df.{log,json}; it binds the tested HEAD and tree. The earlier full suite also passed, before the settlement-scope fix. No Murphy rows closed. This increment completes local creation-intent crash accounting and retains public cost-contract evidence; it does not finish delayed provider cleanup or prove the cumulative USD 5 bound. Activation remains disabled. No workers or paid model calls were launched; no push, main change or merge into factory-simplify occurred.

Remaining increments, incorporating the parent's planning-only item-8 handoff (stream-d.md Item 8 at f431823, not merged by this task):

1. Finish delayed cleanup and cumulative infrastructure cost proof, including provider multiplicity/exceptional billing qualification, cumulative admission and replacement clamps, and launch/deletion evidence.
2. Legacy ownership and deployment inventory, plus eligible authenticated inputs and migrated-store qualification.
3. Router provisioning and the cheap plumbing profile, preserving production role restrictions.
4. Reviewed policy and release pins, the reviewed execution manifest, and cross-release carry-over qualification (row new-batch-service-4).
5. Separate account-2 attribution qualification.

Item 8 uses sequential throwaway workers, each deleted and verified before the next one. Worker reuse is not required. These are later qualification obligations, not claims satisfied by the current offline tests.

