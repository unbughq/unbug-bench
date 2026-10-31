**FAIL.** One blocker and three majors are still open. The B1 option (a) fix holds for the SIGKILL case. The Major 2 and Major 3 fixes are in place. The residual provider lock boundary is stated correctly. But making only the resume path clear the marker opens a new gap when the controller is sent SIGTERM. The full review is below for you to save as `docs/reviews/stream-b-creation-intent-design-2.md`. I made no edits.

---

# Goldfish design review 2: `docs/designs/stream-b-creation-intent.md`

**Reviewer:** fresh goldfish, read-only, no parent context. **Mode:** REVIEW. **Personas:** `zoom_out`, `design_critic`, `implementation_readiness`. **Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`, and `zoom-out-standard.md` (required by `zoom_out.md`).
**Tree:** worktree `t3-ded79ec5` at `6f30f8d`. The design, review 1 and `docs/reports/stream-b-cost-contract-20261031/` are untracked. No code is implemented yet.
**Read:** the design; review 1; `docs/ENGINEERING.md`; `bin/boat-launch-guards.sh`; `bin/boat-call`; `bin/processes.py`; `bin/exam-launch`; `factory/control_resume.py`; `factory/launch.sh` (365–430, 640–660); `factory/batch_holder.py` (20–35, 255–400, 500–530); `tests/factory/test_isolation_timeouts.py` (30–45, 330–445) and its fixtures; the test index of `tests/factory/test_control_resume.py`; Murphy rows 6, 27, 28, 29, 35 and 51.
**Experiment:** a throwaway `/tmp` script, with no workspace writes. A `sh` controller with `trap '…; exit 143' TERM` was sent SIGTERM while it ran `( sleep 2; echo created ) > out` in the foreground. The trap ran about 2 s after the kill, after the subshell finished. The line after the subshell never ran.

## Verdict: **FAIL** (1 blocker, 3 majors, 5 nits)

## Verification of review-1 fixes

**B1, option (a): verified for the SIGKILL case it targets.**
- `control_resume.py:71` makes `controller.lock` inheritable, then execs `sh` (line 74). The `( … boat new … )` subshell and the `boat-call` Python process inherit the fd. So a surviving `boat-call` blocks `resume_controller` (`batch_holder.py:520-521`) and `control_resume.py:52` until it exits. Design lines 44–46 are correct.
- **Residual boundary verified.** `processes.run` starts the provider with `start_new_session=True` and the default `close_fds=True` (`processes.py:110-111`). The provider therefore holds no lock fd. It does inherit `boat-call`'s stdout, which is the `new.N` redirect. So a provider that outlives a SIGKILLed `boat-call` can still append to `new.N` after a resume has read it.
- The design handles both orders safely:
  - missing or partial identity keeps the marker (lines 43, 48);
  - a late second `created` event falls under the declared multiplicity residual (lines 49–51, 62–63).
- This residual is stated correctly and blocks activation. I accept it.

**Major 2 (stale `$id`): verified.** Line 24 clears `id` and `new_status` on entry, before any return. Test 3 covers serial 2 failing after serial 1 succeeds.

**Major 3 (kill targets, holder consumer): verified.**
- Test 1 now names both kill targets: the controller PID plus the transport group, and the controller PID alone.
- It asserts that `holder.reconcile` stays `pending` when the locks are free. `_reconcile_one`'s `glob('new.*')` (`batch_holder.py:350`) matches both `new.N` and `new.N.pending`, so a crash between the marker fsync and the `> new.N` open is also held `pending`.

**Nits 1–7: all applied.**
- Row 29 is listed.
- The cost section uses `BOAT_TYPE` rates and mentions Hetzner.
- The fsync mechanism is named.
- `ids` is replaced atomically.
- Test 3's injection is named.
- The Impact and Timeline lines are present.
- Test 4 strengthens the existing test.

## BLOCKER 1: if only the resume path clears the marker, SIGTERM during a successful create leaves a hold reserved for good

- **Affected scope:** lines 41–46 ("On resumed guard_exit… Only the resume path resolves old markers"). Also lines 67–68 ("including non-batch guard callers").
- **Finding:**
  - The controller sets `trap 'exit 143' TERM` (`boat-launch-guards.sh:18`).
  - A POSIX shell runs that trap only after its foreground command finishes. I reproduced this above.
  - Suppose SIGTERM is sent to the controller PID alone (`kill <pid>`). `boat-call` and the provider are not signalled. The create finishes and writes a valid `created` event to `new.N`.
  - Then the trap exits straight into `guard_exit`, and `guard_new`'s clearing code after the call never runs. Under this design the live `guard_exit` does not resolve markers, so `new.N.pending` survives, `unfinished=1`, and there is no `boat-spend --finish`.
- **Today:** with no marker, `guard_exit` picks up the ID through `guard_ids`, retires the VM and finishes. The change regresses that.
- **Batch path:** a later holder resume repairs this.
- **`bin/exam-launch` and other callers with no saved state:** no `UNBUG_LAUNCH_STATE`, so `guard_exit` runs `rm -rf "$state"` (line 280).
  - That deletes the marker and `new.N`, the only evidence that the ID was known.
  - The spend reservation stays `reserved`. The previous increment made expired holds stay reserved, so this is a permanent capacity leak that someone has to clear by hand. That is a pit stop under §3.
- **Why the restriction isn't needed:** a live `guard_exit` already has the quiescence that the lock gives a resume.
  - The trap cannot run until the foreground create subshell has exited.
  - `guard_exit` kills and waits for background jobs first (lines 231–234).
  - The only remaining residual is the same detached-provider case already accepted.
- **Required:**
  - Apply the same resolution rule in every `guard_exit`, live or resumed, before the `unfinished` scan. State the quiescence argument for each case: foreground wait for the live shell, the reacquired lock for a resume.
  - Add a test for a caller with no saved state. Send SIGTERM to the controller PID only while the fake transport is inside `new`. The transport then emits the saved `created.json` and exits. Assert that the marker clears, the ID is in `ids`, and `--finish` is reached after the replayed deletion evidence. Assert also that the variant where no ID arrives still does not finish.

## MAJOR 1: building the merged ID list fails open, and test 3's own injection triggers it

- **Affected scope:** lines 35–36 and 54–56 (merged-ID persistence); test 3 (lines 128–131); `guard_exit`'s marker scan.
- **Finding:**
  - `guard_ids` reads every `new.*` path, including `*.pending`, with `path.read_text()` (`boat-launch-guards.sh:60-61`).
  - Test 3 pre-creates a directory at `new.2.pending`. At the next `guard_ids`, which is in `guard_exit` after serial 2 is refused, Python raises `IsADirectoryError`, prints nothing and exits 1.
  - The status is ignored today (`guard_ids > all-ids` then `cp`). So `ids` becomes empty and serial 1's VM drops out of retirement and the orphan check.
  - The pending scan uses `[ -f ]` (line 263), so the directory marker doesn't count either. `unfinished=0`, so `boat-spend --finish` runs with an empty ID list while serial 1's VM may still be running.
  - The design says only that the helper replaces the `cp` atomically, and that "persistence step" failures fail. It doesn't say that a failure while computing the merged IDs must fail, or that a non-regular marker counts as pending. An atomic rename of an empty list is still fail-open. The same applies outside tests to any unreadable `new.*` (EIO, permissions).
- **Required:**
  - Specify that a non-zero `guard_ids` (or any read or parse failure while merging) prevents both persistence and finish.
  - Specify that the merged list must be a superset of the existing `ids`.
  - Make `guard_exit` treat any existing `new.*.pending` path (`-e`, not `-f`) as unfinished.
  - Test 3 must also run `guard_exit` and assert: serial 1's ID is still in `ids`, there is no `finish` and no `complete`.

## MAJOR 2: the persistence-failure contract can't be built as written and leaves `$id` undefined

- **Affected scope:** lines 37–39 and 51–52 ("Failed local persistence must prevent finish, even if an unlink succeeded before directory fsync failed").
- **Finding:**
  - Once the unlink has succeeded, nothing on disk tells `guard_exit` that the directory fsync failed. The design forbids a new journal, and it names no flag. An implementer must invent a mechanism, which breaks the zero-decision rule, or drop the guarantee.
  - The clause is also stricter than safety needs. The order is: `new.N` fsync, then durable `ids` rename, then unlink. So when the unlink succeeds, the identity is already durably known. Finishing after that ID's `.deleted` is correct. An unlink that a crash undoes only brings the marker back, and the next run clears it again with the same result.
  - Also unspecified: is `$id` set when persistence fails after a valid ID?
    - If it is empty, the `launch.sh:650` failure branch skips retirement. The loop then moves on to more serials while that VM runs until exit.
    - If it is set, the VM is retired at once.
- **Required:**
  - Delete the "even if an unlink succeeded…" clause, and state why it is safe: `ids` is durable before the unlink. Otherwise, name the exact mechanism.
  - State that `id` holds the valid created ID whenever one was read, even when persistence fails, so the launcher's failure branch retires it.

## MAJOR 3: the test harness that proves the lock-inheritance claim is not chosen

- **Affected scope:** test 1 (lines 111–124), "Resume guard_exit in a fresh process" and "Assert the lock prevents early resume".
- **Finding:**
  - The claim under test is that `control_resume.py`'s inheritable lock, via exec, covers the shell, the subshell and `boat-call`.
  - The existing `test_isolation_timeouts.py` pattern sources the guards in a bare `sh -c` (lines 384–389). That has no `controller.lock` at all.
  - A test that takes its own `flock` would be a fixture written to match the code under test. It proves nothing about `control_resume`.
  - "Replayed deletion evidence" also has no source in `fixtures/isolation-timeouts/`. The fixtures there are billing, version, created, launch, list, monitor, scorecard and worker-release.
  - `tests/factory/test_control_resume.py` already runs `launch.sh --resume-launch` through `control_resume.py`. It kills with `SIGKILL`/`killpg` (lines 123–155) and replays `deletion-completion.json` receipts (line 165).
- **Required:**
  - Say that test 1's kill and resume steps go through the real `control_resume.py` exec path. Reuse the `test_control_resume.py` harness, or name the file where these cases live.
  - Name the deletion-receipt source that it replays.
  - If the tests must stay in `test_isolation_timeouts.py`, say exactly how they acquire and inherit the lock.

## Nits

1. **Wrong process description, line 112.** "boat-call creates its own session" is inaccurate. `boat-call` stays in the controller's process group. `processes.run` puts the provider in a new session. Test 1's first case therefore leaves `boat-call` alive until the killed provider is reaped. That is harmless, but write it down so the test doesn't hang waiting on the wrong PID.
2. **A third non-atomic `ids` rewrite.** `factory/launch.sh` resume branch (around 643–644) also runs `guard_ids > all-ids; cp all-ids ids` in place, on every resume. That is exactly where a reuse-worker ID that `new.*` can't rebuild is exposed. Route it through the same helper.
3. **Test 3 harness, line 130.** "No retirement of serial 1 through the launcher failure branch" needs either `launch.sh` itself or an assertion on `$id` after `guard_new`. Say which. A copied loop would be self-generated.
4. **Test 1, "may retain the … incident", lines 118–120.** Make it deterministic. After a resume that cannot resolve the creation, assert the exact holder outcome: `pending`, with `failures` incremented. Don't write "may".
5. **Altitude.** The cost-qualification section (lines 70–103) is evidence for a later increment and changes no code here. It is accurate and properly hedged. I checked it against `sources.json` and the pages in review 1, and nothing has changed. Consider moving it to the cost-contract design so this doc stays at the crash-ordering level.

## What passes

- The problem is real and verified in code. The scope is minimal: the existing marker name is reused, the late `touch` is deleted, and there is no journal, supervisor or adapter.
- The live persistence order (exclusive create, then fsync of file and directory, then the call, then durable `ids`, then unlink and directory fsync) is correct.
- Exclusive creation with no truncation and no replay is correct.
- The detached provider and CLI multiplicity residuals are stated honestly and keep activation closed.
- Heilmeier: the plain Impact, Cost and Timeline lines are present, the risks are named, and the tests act as exams.
- There is no change to section 4 or to any security property. The design correctly says no Murphy rows close, and lists rows 6, 27, 28, 29, 35 and 51 as open.

**To pass:**
- Blocker 1: resolve markers in every `guard_exit`, and add the SIGTERM test for a caller with no saved state.
- Major 1: make merged-ID computation and the pending check fail closed.
- Major 2: specify, or drop, the after-unlink clause, and specify `$id` on persistence failure.
- Major 3: name the `control_resume` test harness and the deletion-receipt source.

## Elephant response

Accepted blocker 1 and majors 1–3. All exit paths resolve known identities; merge errors retain prior IDs and block finish; any pending path blocks finish; post-unlink fsync failure does not invalidate already durable identity. The live id survives persistence errors. Tests use test_control_resume and its existing saved deletion receipts. Nits 1–4 accepted; cost section retained here to keep this increment's evidence and remaining scope together. No blocker rejected. Fresh design review follows.

