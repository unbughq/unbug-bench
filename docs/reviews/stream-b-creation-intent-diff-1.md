I'm returning **FAIL** with one blocker. The crash fix itself holds up; the blocker is a missing proof plus an unreviewed change to when money settles. The full report is below for you to save as `docs/reviews/stream-b-creation-intent-diff-1.md`. I made no edits in the worktree.

---

# Goldfish diff review 1: `stream-b-creation-intent`

**Reviewer:** fresh goldfish, read-only, no parent context. **Mode:** REVIEW. **Personas:** `zoom_out`, `implementation_readiness`. **Standards:** `implementation-readiness-standard.md`, `zoom-out-standard.md`.

**Tree:** worktree `t3-ded79ec5`, branch `t3/batch-service-control-vm`. The diff is `6f30f8d..f30eb12`, which is one commit: "Persist creation uncertainty before provider submission".

**Read:**
- `docs/ENGINEERING.md`, the persona files and the standards.
- The design and design reviews 1–3.
- The diff to `bin/boat-launch-guards.sh`, `factory/launch.sh`, `tests/factory/test_control_resume.py`, `test_isolation_timeouts.py` and `test_codex_login_rotation.py`.
- `factory/control_resume.py` (the lock and exec), `bin/boat-spend` (holds) and the `ControlResumeTests.setUp` harness.
- The suite log and its JSON record.
- The cost-contract pages and `sources.json`.

**Independent checks (all in throwaway `/tmp` copies, never in the worktree):**
- I extracted `git archive HEAD` to `/tmp/goldfish-ci.7GUW` and ran `CreationIntentTests`: 5 tests passed.
- I ran mutations against `test_control_resume` (`CreationIntentTests` or the whole module) together with `test_isolation_timeouts`.
- I recomputed the log SHA256: `e2fb4e6a…01da`. It matches the JSON. The log shows 158 scripts, 0 failed, and `test_control_resume` ran 20 tests.
- All six cost pages match their SHA256 in `sources.json`.
- `docs/murphy-register.md` is unchanged.

## Verdict: **FAIL** (1 blocker, 0 majors, 8 nits)

## Verification of the design-review fixes

**Review 1, B1 (resume resolves a known identity): verified.**
- `guard_exit` now calls `guard_ids resolve` before the pending scan. The resume branch in `launch.sh:638` calls `guard_ids persist || exit 1`.
- `test_surviving_creator_holds_lock_then_resume_finishes` kills only the controller PID. The early resume fails with "already owned", which comes from `control_resume.py:52` through the inherited lock fd. After the provider is released, the next resume clears the marker, retires the worker through the real `guard_delete_receipt`, finishes and writes `complete`. A further resume makes no provider calls at all.
- Mutation: replacing the exit-time `resolve` with `persist` fails this test and the SIGTERM test.

**Review 1, Major 2 (stale `$id`): verified.**
- `guard_new` clears `id` and `new_status` on entry, before any return.
- The test sets `id=stale` and then hits a refusal on an existing response and on a directory marker. It asserts `id` is empty after `guard_new`.

**Review 1, Major 3 (kill targets, holder): verified.**
- Test 1 kills the whole controller group with `killpg`, then the provider session. Test 2 kills the controller PID alone.
- The crash artifacts are copied into the holder fixture. `reconcile` then gives `pending/creation_unknown`, and `failures == 1`.

**Review 2, B1 (live SIGTERM): verified.**
- `test_sigterm_live_exit_resolves_or_retains_without_saved_state` covers both outcomes.
  - With an ID: exit 143, the ID ends up in the spend record, deletion completes, finish happens and the state is removed.
  - With no ID: the marker is kept and finish does not happen.
- This matches the trap-ordering argument in the design.

**Review 2, Major 1 (merge fails closed): partly verified. See Blocker 1.**
- The merge reads only files matching `new\.[0-9]+`.
- It starts from the existing `ids`, so the result is a superset.
- A read error keeps the old `ids`.
- The pending scan uses `-e` or `-L`. Mutating it to `-f` fails a test.

**Review 2, Major 2 (`$id` on persistence failure): verified.**
- `id` is set before `guard_ids resolve`, and `guard_new` returns 1 with `id` still set.
- `test_merge_failure…` asserts `1:<saved id>`, with the marker kept and the prior `ids` unchanged.

**Review 2, Major 3 (real harness): verified.**
- A fresh launch runs `launch.sh`, which execs `control_resume.py`, which execs `sh`.
- `boat-call` is copied from the real file, and the provider runs under `processes.run`.
- The deletion responses are authored and labelled as authored.

**Crash ordering in the code: correct.**
1. Refuse if `new.N` already exists (`lexists`).
2. Create the marker with `open('x')` (`O_EXCL`; this also refuses a dangling symlink).
3. fsync the marker, then fsync the directory.
4. Call `boat new`.
5. fsync each response that has an ID.
6. Write `ids` to a temp file, fsync it, rename it over `ids`, fsync the directory.
7. Unlink only regular-file markers, then fsync the directory.

The provider-side assertion `new.1.pending is_file()` proves that step 2 happens before submission, through the real wrapper.

## BLOCKER 1: the "merge failure blocks finish" property is unproven, and the code that implements it also blocks finish on every other cleanup error

**Affected scope:**
- `bin/boat-launch-guards.sh`, `guard_exit`: the new line `[ "$guard_cleanup_failed" = false ] || unfinished=1`.
- `tests/factory/test_control_resume.py::test_merge_failure_keeps_prior_ids_and_reported_id`.

**Finding:**

1. **No test proves it.**
   - The design requires that "On merge failure guard_exit … marks cleanup failed and blocks finish".
   - Mutation: I deleted that one line. All 27 tests in `CreationIntentTests` plus `test_isolation_timeouts` still pass.
   - The merge-failure test cannot detect the loss, for three reasons:
     - `new.1.pending` is still present, which blocks finish on its own.
     - The test stubs `guard_retire() { return 1; }`, so `existing-reuse-worker` has no `.deleted`, which also blocks finish.
     - The stub also bypasses the step the design asked to "Test that failure explicitly": Boat's ownership check in `guard_delete_receipt` refusing a worker that is not in `ids`.

2. **The line changes money settlement beyond the reviewed design.**
   - The design blocks finish on ID computation or persistence failure. The code blocks it on *any* `guard_cleanup_error`. That now includes:
     - a failure of the orphan-check `boat list`;
     - an orphan status match after a verified deletion;
     - a failure of `factory_ttl_retired`.
   - None of these blocked finish at `6f30f8d`.
   - **Callers with no saved state** (`exam-launch`, run with `UNBUG_CLOUD=boat`): one transient `boat list` failure now keeps the temporary state and never runs `--finish`. In `bin/boat-spend`, a reserved hold never expires (only `status == 'reserved'` counts; there is no expiry release). So the reservation consumes capacity until someone clears it by hand. That is a §3 pit stop that no review weighed.
   - **The declared residual case:** suppose a surviving provider appends a valid non-object JSON line to an already-resolved `new.N`. The merge now fails on every exit, so that hold also stays reserved for good. That outcome is fail-closed, but it is not written down.

**Required (pick one, then write it into the design):**
- **(a)** Narrow the block to merge failure only. Set `unfinished=1` only when `guard_ids resolve` fails. Leave the other cleanup errors with their `6f30f8d` finish semantics.
- **(b)** Keep the broad block deliberately. State it in the design, together with its money and pit-stop consequence for callers with no saved state.

Either way, add a test that isolates it:
- The serial-1 worker is in `ids` and retired with `.deleted`.
- No pending marker exists.
- `new.9` is unreadable.
- `guard_exit` must then not finish and must not write `complete`.

Also replace the `guard_retire` stub with the real ownership refusal, so the design's "test that failure explicitly" is met. Nothing beyond the deletion of the single line above should make this test fail.

## Nits

1. **The non-object JSON fail-closed rule is untested.** Changing `raise ValueError('invalid event')` to `continue` survives all the tests. Add one line, such as `42`, to an otherwise valid response, and assert that the merge fails and nothing finishes.
2. **The `launch.sh` resume propagation is untested.** No test covers `guard_ids persist || exit 1` failing. The design says it "must propagate merge failure". In practice the leftover markers mask it, but there is no proof.
3. **Test 1 doesn't assert the resume route.** Neither of its two resumes checks the return code or stderr. A resume that refused early, for example with "launch initialization incomplete", would still satisfy `assert_unfinished`. Test 2 shows that the same setup does reach `guard_exit`, so this is a nit. Assert a nonzero exit and the "pending reconciliation" or cleanup message.
4. **The holder count uses a constant.** The test passes `rc=1` to `record_child` instead of the resume's real exit code. Feed it `self.resume().returncode`.
5. **Test placement and coverage differ from the design.** The design put test 4 in `test_isolation_timeouts` and asked for status 0 and status 9 through `guard_new`. The tests live in `test_control_resume`, and only status 9 goes through `guard_new`'s own resolution. Status 0 is covered only through the `guard_exit` path. The code path is shared, so this is low risk.
6. **There is no dangling-symlink marker case.** The `-L` branch and `open('x')` refusing a symlink are untested. A directory marker is tested.
7. **The fsync steps cannot be proven by a test.** Mutating the response fsync to `pass` survives. That is expected without fault injection. Just don't claim the fsync steps are tested.
8. **The suite record isn't tied to the tested tree.** The JSON has `"base": "6f30f8d"` but no HEAD or tree hash. The run ended at 12:31:13Z and the commit is at 12:31:37Z, so it is plausible the suite ran on this tree, but the record doesn't prove it. Add `git rev-parse HEAD` or `git write-tree`. My own run of the affected modules on `f30eb12` passed.

## Zoom-out

- **Scope is minimal.**
  - It adds one inline intent helper and one merge/persist/resolve helper with three modes.
  - It deletes the three in-place `cp` rewrites and the late `touch`.
  - It adds no journal, supervisor, adapter or replay.
- **Reuse.** The design and review 3 already established that no existing durable-replace helper is usable from shell.
- **Rules.** It changes no §4 rule and no security property.
- **Side change.** `test_codex_login_rotation` changes one line, because `guard_ids` now writes `ids` itself. It is needed and correct.

## Money, cost and remaining scope

- **Hold safety.** The reserved hold is unchanged on every unknown or uncertain path, as checked by `assert_unfinished` against the ledger. Finish happens only after the real receipt verifier sees a `completed` deletion.
- **Cost claims.** All six pages match their hashes. The rates ($0.018/0.036/0.072/0.200 per hour), extra starts up to $0.07 and no egress charge match `pricing.md` and `limits.md`. The design claims no USD 5 bound and enables nothing.
- **Honest claims.**
  - No Murphy rows close; rows 6, 27, 28, 29, 35 and 51 stay open.
  - There is no live proof or live deletion qualification.
  - Activation stays gated on the detached provider and CLI multiplicity residuals.
  - The remaining increments are listed.

**To pass:** resolve Blocker 1. Either narrow the block or document it, and add the isolated merge-failure test with the real ownership refusal. The nits are optional.

## Elephant response

Accepted B1, option (a): narrow the new finish block to creation-evidence computation/persistence errors. Preserve baseline settlement for unrelated cleanup errors. Add an isolated no-pending, already-deleted worker regression and exercise the real Boat ownership refusal separately. Add non-object JSON and dangling-symlink exams, direct status-0 success and resume failure propagation. Assert the actual unknown-resume route and feed its real exit code to record_child (the existing empty-ID resume exits 0 but remains incomplete and counts as a failure). Record HEAD/tree on the new full suite. fsync ordering is code-reviewed, not claimed as experimentally proven power-loss durability. No blocker rejected; a fresh reviewer must verify the fix after the new full suite.

