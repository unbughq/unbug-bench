# Stream E loaded cleanup: fresh diff review

Reviewer: Claude claude-opus-5-5, fresh read-only goldfish, Mode: REVIEW.
Reviewed commit: 41b90bb, base b500db9.

**Verdict: FAIL.** The code is right. Two small register fixes are needed before the Murphy row can be closed.

## What I checked
- **Are the production changes needed?** Yes. The old 2 s `ps` probe skipped the descendant snapshot under load, so nested sessions survived. The old `killpg` also raised EPERM on macOS for groups that hold only zombies, which made `boat-call` exit 1. Both are fixed at the shared spot, `processes.kill_tree`, so every caller gets the fix. No new helpers or abstractions were added, so the diff stays minimal.
- **Process-group ownership and cancellation:** still correct. The snapshot still happens before any kill. Our own group and session are still excluded. `os.kill` stays strict. If the probe times out, the code still kills the owned group. The cost is that a timed-out child can keep running up to about 60 s past its deadline while `ps` runs. That trade is acceptable because it only happens when `ps` really is slow.
- **Waits under load:**
  - In the tests, the walls that only guard against hangs are now 300 s or 900 s. The only deadline still under test is the 10 s deletion deadline for the `deletion-incomplete` mode. That is appropriate.
  - In `bin/boat-launch-guards.sh:128`, the outer wall is `remaining + 70`. It covers one cleanup of up to about 64 s (60 s probe, then two 2 s waits). It is tight: with the real `boat` executable, `boat-call` does a `--version` run before the command, and that leaves only about 6 s for interpreter startup at load ~500. See nit 2.
- **Does the new test prove the fix?** `test_loaded_host_slow_ps_and_zombie_group_still_clean_up` fails on the old code in both halves:
  - **Slow `ps`:** the stub `ps` takes 3 s, longer than the old 2 s bound. The old code skipped descendants, so the nested child (which ignores SIGTERM) kept writing its heartbeat and `stopped()` fails.
  - **Zombie group:** the old code raised an uncaught PermissionError on macOS.
  
  Watching the zombie through polled `ps` is bounded, and the zombie is always reaped. On Linux the zombie half proves nothing, but the bug only happens on macOS.
- **Evidence:** five loaded launch-guard and isolation pairs passed at `8ff8606`, and the full suite ran 155 scripts with 0 failures. That is consistent with the claims.

## Blocking findings
1. **The Murphy row says EPERM is tolerated more narrowly than the code tolerates it.**
   - Where: `docs/murphy-register.md`, row `new-isolation-load-1` ("tolerate EPERM only from `killpg` on zombie-only groups"), and the comment at `bin/processes.py:49-52`.
   - Problem: `_killpg` ignores every PermissionError from `killpg`, not just the zombie-only case. Production does create process groups owned by other users: model calls run under `sudo -u <user>` (`factory/model_runtime.py:554, 596, 608`).
   - Effect: if one of those times out, cleanup now silently leaves that group alive. Before this change, it raised. In practice the separate `sudo pkill -KILL -u <user>` cleanup covers it (`factory/model_runtime.py:666`, `factory/run_artifacts.py:153`, `factory/run.py:2488/2531`). But the closure statement is false as written, and the test only proves the zombie case.
   - Fix: change the row and the comment to say all EPERM from `killpg` is ignored, and that groups owned by other users depend on the per-user `pkill`. Alternatively, narrow the code to match the row. The doc fix is enough.
2. **The second Murphy row sits outside the table.**
   - Where: `docs/murphy-register.md`. There is a blank line between `new-isolation-load-1` and `new-isolation-waitid-1`.
   - Effect: the blank line ends the Markdown table, so `new-isolation-waitid-1` shows up as a stray paragraph, not a register row.
   - Fix: delete the blank line.

## Nits (not blocking)
1. **Other `boat-call` callers have outer walls no longer than its internal deadline.** This pre-dates the diff, but the diff makes the window bigger:
   - `factory/key_holder.py:658` uses a 25 s wall, against `boat-call`'s default of 120 s.
   - `factory/ttl_continuation.py:87` uses 120 s, the same as the default.
   
   The cleanup tail after the deadline was about 6 s and can now be about 64 s. When the outer `subprocess.run` timeout SIGKILLs `boat-call` partway through cleanup, the Boat child keeps running in its own session. Worth a Murphy row. Only the launch guard's wall was widened here.
2. **Thin margin at `bin/boat-launch-guards.sh:128`.** The `+70` leaves about 6 s for `boat-call` interpreter startup on a loaded host, because the remaining time is computed before `boat-call` starts and its deadline begins after startup. The code comment should mention that `boat-call` can do a `--version` run before the command.
3. **`bin/processes.py:78` has an unbounded wait.** After `_killpg(probe.pid)` it calls `probe.communicate()` with no timeout. That is safe because `ps` has no children, but it breaks the file's "never drain forever" rule. `communicate(timeout=2)` would keep it consistent.
4. **The `f952418` commit message says "kill the probe by PID".** The code still kills the probe's whole group, which is the same as its session because it starts with `start_new_session=True`. The Murphy row's wording is the correct one.

## Implementation response

Accepted both blocking findings; none rejected. Clarified the Murphy closure and the _killpg comment: all killpg PermissionError is suppressed to tolerate macOS zombie-only groups, and cross-user model processes still require the existing privileged per-user pkill cleanup. Removed the blank line so the waitid portability row remains in the register table. These are documentation/comment corrections only; executable behavior is unchanged from tested source 8ff8606.

Recorded the pre-existing outer-wall mismatch in open Murphy row new-isolation-outer-wall-1. Clarified the deletion guard comment to mention boat-call's preliminary version check. Left the optional unbounded post-SIGKILL ps drain nit unchanged: the production ps probe has no children and its owned group has just been killed; changing cleanup behavior is outside these documentation fixes. The final register correctly describes group signalling, superseding f952418's PID wording. No blocking finding remains unaddressed; no finding was rejected. The original review verdict is retained verbatim above.

