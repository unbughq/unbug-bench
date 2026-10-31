**FAIL.** Commit 150800a follows the activation readiness addendum closely, and it integrates cleanly with the merged b500db9. One code gap and two tests that prove nothing still block it.

What holds:
- `failures` is durable, it is validated in the shared `validate_operations`, and the two new incidents are whitelisted. The money-state accounting reasons are unchanged.
- `batch_tick` backs off 60/120/240/480 s and clears the wait when it respawns.
- The lost-exit probe does not block, so it is deadlock-free (design-2 N1).
- The `publish` child zeroes its identity buffer in the shared `finally`.
- Chain-head status replaces the whole old `active` block as design-2 required.
- `budget.py` and `diagnosis.py` are now in `TRUSTED_FILES`. The publication import path (`collection_facts` → `budget.case_spending`/`usage_coverage` → `diagnosis._uuid4` → recovery/budget/registry) only reaches trusted files.
- The merge's `_charge`/`_extends` changes and the budget/diagnosis changes do not conflict with this increment.
- The commit changes no Murphy rows, which matches the addendum's "None closed".

## Blockers

**B1. A launch that fails before `guard_init` stays `pending` forever, with or without a recorded exit.**
- **Where:** `factory/batch_holder.py:339-346` (`_reconcile_one`). The predicate reads `ids` with `service._regular(path / 'ids')`.
- **Why it matters:** `ids` only exists after `guard_init` runs `: > "$state/ids"` (`bin/boat-launch-guards.sh:14`, called at `factory/launch.sh:365`). `control_resume.py` writes `launch.json` and then runs launch.sh. Launch.sh has many plausible ways to exit before line 365, for example:
  - secrets decryption fails (`launch.sh:143`);
  - `restore-check` refuses (`:193`);
  - the job config or batch release checks fail (`:62-81`).
- **Result:** the launch directory has a matching `launch.json`, a free `controller.lock`, no `new.*` and no `ids` file. Reading `ids` raises `OSError`, the code swallows it, and the operation stays `pending` forever. It keeps the slot and shows only `launch stuck`. Problem 1 of the addendum is not solved for the most likely real failure.
- **Why the tests miss it:** the `started()` helper writes an empty `ids` file (`tests/factory/test_batch_holder.py:69`), which is not what a real VM layout looks like.
- **Remedy:**
  - In the probe, treat a missing `ids` as empty: catch `FileNotFoundError` and use `''`, but only after the `controller.lock` flock and the `new.*` glob have both passed.
  - This is safe: a live launch.sh holds `controller.lock` through an inherited descriptor, and `guard_new` always leaves a `new.*` file before any worker is created.
  - Add a test that builds the layout control_resume really leaves behind (mkdir + `launch.json` + `controller.lock`, no `ids`) and asserts `failed`/`preflight_refused`.

**B2. The fence test passes even without the fence (addendum test 3).**
- **Where:** `tests/factory/test_batch_holder.py`, `test_lost_dispatch_exit_fails_without_a_recorded_exit`. It runs `control_resume.py noop` and checks only `returncode != 0`.
- **Why it matters:** with no fence, `control_resume` would `mkdir`, take the lock, write `launch.json` and exec `launch.sh noop`. That exits 1 with "N must be a positive integer", so the assertion passes either way. The property that matters most for money ("a late launch.sh can no longer start a worker") is not tested.
- **Remedy:**
  - Assert that the refusal comes from the `mkdir` (`FileExistsError` in stderr).
  - Assert that the fenced directory still has no `launch.json` and no `controller.lock`.
  - Use a valid argv such as `['1']` so that only the fence can cause the refusal.

**B3. The new secrets path in `publish` has no test at all (addendum test 4).**
- **Where:** `factory/batch_holder.py:422-446` (`_r2_env`) and `main`'s `publish` branch (`:711-716`).
- **Why it matters:** the design asked for "the real `publish` command path (secrets decryption is a double at the age boundary)" and "a refused first publication (transport raises)". The test instead:
  - replaces `_r2_env` whole (`return_value={}`), so the `age|tar` pipe, the `tar -xOf - r2-env` member name, the `shlex` parsing of the real `bin/setup-secrets:77` format and the four-key check never run;
  - calls `publish_replay` directly rather than through `main`, so the argparse `publish` choice and the identity zeroing are untested;
  - never makes a first publication fail.

  This is new code that handles secrets and runs in the live practice run. If it is wrong, every replay fails and the operation ends `publication_failed` after about 15 minutes.
- **Remedy:**
  - Put a stub `age` executable on `PATH` that writes a real tar holding an `r2-env` built exactly as `bin/setup-secrets` builds it.
  - Run `batch_holder.py publish --operation <id>` as a subprocess (or `main()`), with identity bytes on stdin and `r2_publish`/transport as the only network double.
  - Assert the ACK and the pointer.
  - Add one case where `collect` first fails in transport (outbox `pending`, no ACK), then `unpublished` lists the operation and replay succeeds.

## Majors (non-blocking; fix or record a decision)

- **M1. A stale output is never replayed** (`unpublished`, `batch_holder.py:404-418`).
  - Restart-in-place collects more than once per launch. If the first collection published generation g1 and the last collection's publication fails, then `output_generation=g1` is not null. The operation is never listed, and status shows the stale g1 card as `stopped`.
  - It is money-safe, because the full hold stays committed.
  - Remedy: also list an operation whose `outbox/<id>.json` exists with `state != 'acknowledged'`, or state this ceiling in the design.
- **M2. Test 1 does not prove the backoff or that the count survives a restart.**
  - The loop runs `waits.clear()` on every pass, so the 60·2^(n-1) windows are never asserted.
  - The "holder restart" check runs only after the operation is already terminal, where no respawn could happen anyway.
  - Remedy:
    - assert `waits[op] - now ≈ 60, 120, 240, 480`;
    - restart with fresh `children`/`waits` after two failures and assert the third failure gives `failures == 3`.
- **M3. Test 6 was not delivered as designed.**
  - N5 still uses a mocked `reconcile` (`side_effect=OSError('authored corrupt money')`, `:426`). The design asked for the real `reconcile` with a corrupt `money.json`.
  - N4 tests only the refusal; no test shows `serve` accepting `$UNBUG_CONTROL_HOME/policy.json`.

## Nits

- **N1.** Resume and publish share one `failures` counter. It resets only when a resume child finishes its job. A controller finished by hand after four resume failures reaches `publication_failed` on its first publish failure, and the 480 s resume wait also delays the first publish spawn. Fix by resetting the counter when `unpublished` first lists the operation, or by accepting and documenting it.
- **N2.** `record_child` returns 1 on `BlockingIOError` (`:282`). Another process's `reconcile` probe can briefly hold the operation lock, so a refused exit can go uncounted. This is rare, and the result is only an extra retry.
- **N3.** `publish_replay` does not re-check `complete`, the incident, or `output_generation is None` while it holds the lock. It relies on the scan. `collect` is idempotent, but a duplicate re-uploads to R2.
- **N4.** `test_publication_replay_and_terminal` calls `publish_replay` inside the test process. That sets `os.environ['UNBUG_LAUNCH_STATE']` and leaves it set for later tests. Patch `os.environ` with `patch.dict`.
- **N5.** Design-2 N2 (old `reservations.json` without `failures` is rejected) and N3 (a gone worker shows as `running` during the publish window) are still true, and the addendum does not mention either. Add one line about each.

## Test limitations

- I ran these at HEAD 9d39185:
  - `tests/factory/test_batch_holder.py`: 44 tests OK
  - `tests/factory/test_batch_status.py`: 14 tests OK
  - `tests/tools/test_launch_manifest.py`: 2 tests OK (the pin includes budget/diagnosis)
- I did not run the full 155-script suite.
- Nothing ran against a real VM, real age or real R2. The guard ordering in B1 comes from reading the source (`launch.sh:143/193/365`, `boat-launch-guards.sh:14`). I did not run launch.sh to confirm it.
- I treated `docs/reviews/batch-holder-activation-diff-1.md` as incomplete and did not use it as evidence.
- Nothing in the worktree was changed.

---
Reviewer: goldfish (Claude Opus 5.5), diff review of 150800a at HEAD 9d39185, Mode: REVIEW, personas zoom_out + implementation_readiness, implementation-readiness-standard.


## Elephant response (2026-10-31)

Accepted B1, B2 and B3; none rejected. B1 reproduced before the fix with the
real reservation/reconcile code: no-ids early-exit state was pending instead of
failed. The fix checks free controller lock and no new.* first, treats only
FileNotFoundError as empty ids, and leaves nonregular/symlink evidence pending.
The regression checks the pre-guard-init layout, held controller lock, ambiguous
creation record and symlink. B2 now uses valid argv, requires FileExistsError,
and verifies that neither launch.json nor controller.lock appeared. B3 now
enters main's publish branch with stdin, real tar extraction and setup-secrets'
four-line format; only age and network transport are synthetic. It first fails
publication at transport, then proves pending outbox/no ACK followed by replay,
ACK, pointer, acknowledged outbox, and identity-buffer zeroing.

M1 accepted as a documented scope ceiling in the design, not rejected: a later
failed publication after an earlier ACK needs a follow-up before broad rollout.
M2 fixed: the test asserts all four backoff windows, no early respawn and restart
after two failures. M3 improved: real corrupt money now exercises reconcile while
later scans are checked; the canonical serve policy path is shown to reach runtime
setup. That narrow policy-path test does not claim a full live serve integration.
N1 and N5 documented in the design; N2 and N3 remain accepted conservative/idempotent
limitations. N4 fixed with patch.dict environment restoration.

The first full suite at merged 150800a passed all 155 scripts and is committed
in docs/reports/stream-b-activation-suite-20261031.md. The review-fix suite result
will be recorded there separately. No Murphy row is closed and no live gate is
enabled. The incomplete prior diff-1 is replaced by this final report and response.
