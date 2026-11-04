# Independent per-worker retirement

Murphy row 16, partial: the queueing half only. The row stays **open**.

Revision 4 addresses `docs/reviews/independent-worker-retirement-design-1.md`,
`-design-2.md` and `-design-3.md`.

## Problem

`bin/boat-launch-guards.sh` retires workers one after another.

- In `guard_wait`, a single loop walks every worker of a multi-worker launch
  (`factory/launch.sh N`). When a worker is due (DONE, startup failure, stall,
  unreachable, or the TTL margin), the loop runs the retirement work inline
  and only then moves to the next worker. The retirement work is:
  - `factory_ttl_retire`: up to 2 × 120 s of SSH;
  - `factory_auto_resume`: which itself runs `collect_vm`;
  - `guard_retire`.
- `guard_exit` (the exit trap) does the same with a sequential
  `for exit_id ...; do guard_retire ...; done`.
- `guard_retire` is slow by design. `collect_vm` (`factory/collect.sh`) first
  asks a running case to pause. That SSH is bounded by
  `COLLECT_PAUSE_SECONDS` (1200 s), and the pause waits up to 105 × 10 s =
  1050 s for DONE. Chunked transfers follow. A failed collection is retried up
  to 3 times, 30 s apart, so one retirement can take about an hour.
- Workers in one launch are created within minutes of each other, with the
  same `ttl_seconds` and `retire_at`. They reach the TTL margin in the same
  poll. Worker k starts collecting only after workers 1..k-1 finish. Real
  launch layout `tests/factory/fixtures/isolation-timeouts/monitor.json` has
  `margin=1800`, `ttl_seconds=57600` and `retire_at=55800`. The first worker's
  pause alone can use up the second worker's 1800 s reserve. Boat's TTL then
  erases that worker (`--no-snapshots`) unsnapshotted.
- `guard_wait once` runs between worker creations in `factory/launch.sh`. A
  synchronous retirement there also stalls provisioning of the next worker.
- A worker that becomes due on a later poll waits behind any retirement still
  running.

## Change

Every retirement that `guard_wait` used to run inline now runs in that
worker's own background task. That is `factory_ttl_retire` plus
`guard_retire`, and the `.retired` decision.

`factory_auto_resume` (DONE path, `label=factory`) **stays inline**, exactly
as today. If it returns 0, the worker stays pending. If it returns non-zero,
a `retire` task starts. It stays inline because its stop semantics depend on
the launcher trap running between its commands:
- Ctrl-C would otherwise make its `boat-call`s fail inside a shell that
  ignores SIGINT, which runs its `.keep` handlers;
- TERM to the launcher alone would otherwise let it reach
  `boat exec --detach run.py --resume`, which is new paid work after a stop.

Keeping it inline preserves today's behaviour exactly (design review 2,
finding 1).

**Two phases per pass** (design review 3, finding 1). The classification loop
starts a task for every worker due for retirement in this pass. DONE workers
that are auto-resume candidates (`label=factory` and `factory_auto_resume`
defined) are collected into a deferred list instead. Only after the loop does
the pass run the deferred inline auto-resumes, in order. A worker whose
auto-resume returns 0 stays pending; one that returns non-zero gets a
`retire` task.

So a peer that is due in the same pass is never queued behind an auto-resume.
The bound that remains, across passes, is stated under Out of scope.

So the poll loop does probes (bounded by the Boat command timeout),
classification, task starts, deferred inline auto-resume for DONE factory
workers, and reaping.

### `guard_retire_start <id> <kind>`

`kind` is one of:
- `retire`: plain `guard_retire`;
- `ttl`: `factory_ttl_retire` if it is defined (a failure only logs, as
  today), then `guard_retire`.

Steps:
1. Bump a counter, then set `gr_token=$guard_task_epoch.$$.$counter` and
   `gr_exit=$state/$id.retirement-exit.$gr_token`. `guard_task_epoch` is
   `date +%s`, taken once when the guard is sourced. A restarted controller
   that reuses a dead controller's pid therefore still gets a distinct token.
2. Remove older `$state/$id.retirement-exit.*` files. This must happen
   **before** the fork, so the glob cannot remove the new task's own file.
3. Unless `guard_exiting=1`, install deferring traps:
   `trap 'gr_signal=130' INT` and `trap 'gr_signal=143' TERM`.
4. Start the task:
   ```sh
   ( trap - 0
     gr_s=0; <kind work> || gr_s=$?
     printf '%s\n' "$gr_s" > "$gr_exit.tmp" && mv "$gr_exit.tmp" "$gr_exit" ) &
   ```
5. Append `id:pid:token` to the space-separated shell variable
   `guard_retiring`.
6. Restore the traps with `guard_signal_traps`, the same helper `guard_init`
   now calls to install `trap 'exit 130' INT` and `trap 'exit 143' TERM`. If
   `gr_signal` is set, run `exit "$gr_signal"`.

The `ttl` dispatch, inside the `|| gr_s=$?` context, is:

```sh
case $kind in
  ttl) if [ "$label" = factory ] && command -v factory_ttl_retire >/dev/null 2>&1; then
         factory_ttl_retire "$id" || echo "... TTL attestation failed ..." >&2
       fi
       guard_retire "$id" ;;
  *) guard_retire "$id" ;;
esac
```

`ttl` is used only in the numeric-reply branch that reaches the TTL margin,
which is today's only `factory_ttl_retire` call site. The stall branch and
the unreachable-or-TTL-margin branch start `retire`.

The guard file initialises `gr_signal`, `guard_exiting`, `guard_retiring`,
`guard_task_counter` and `guard_task_epoch` when it is sourced, so `set -u`
holds.

This closes the window between `&` and recording the pid. A signal in that
window only sets the flag, and the exit trap then sees the recorded task.
Inside `guard_exit`, INT and TERM are already ignored, so it skips the trap
juggling.

Notes:
- `trap - 0` makes sure the task never runs `guard_exit`. Under dash and
  POSIX, a subshell resets caught traps anyway; this is belt and braces.
- `|| gr_s=$?` keeps the work out of `set -e`, as the old
  `guard_retire ... ||` call sites did. A task that hits a shell-fatal error
  (`set -u`, ENOSPC on the status write) or is killed by a signal ends with
  no status file. The reaper handles that case.
- The token in the file name means a stale file is never read. That covers a
  previous controller and an orphaned task left by a SIGKILLed controller.
  Reap reads only the exact token it recorded. Start removes older
  `$state/$id.retirement-exit.*` files.

### `guard_retire_reap [block]`

For each `id:pid:token` in `guard_retiring`:
1. **Finished?** The task counts as finished if its exit file exists, if
   `kill -0 "$pid"` fails, or if `block` was passed. dash records a finished
   child's status during later foreground commands, so `kill -0` fails once
   it has been reaped.
2. **Reap.** Run `wait "$pid" || :` and read the file.
   - **Numeric status:** touch `<id>.retired`. A status above 0 sets the
     reaper's return value to 1.
   - **Missing or invalid status:** the task died (SIGKILL/OOM, a `set -u`
     abort, ENOSPC). Log it, set the return value to 1 and touch
     `.retired`. This is exactly how a failed retirement is handled today.
     The worker is never re-classified or respawned in `guard_wait`.
     `guard_exit`'s exit pass retries `guard_retire` from its markers, and
     the provider TTL is the final backstop. Today, a shell-fatal error in
     an inline `guard_retire` kills the launcher shell, and the exit pass
     runs **at once**. Now it runs when the batch ends. A TTL-due worker
     whose task died can therefore be erased before that pass reaches it.
     The trigger is rare (SIGKILL/OOM of a small `sh`, a `set -u` bug,
     ENOSPC), and this is an accepted trade-off against re-classification.

     This replaces revision 3's respawn, which re-classified the worker and
     lost its retirement kind (design review 3, finding 2). It also cannot
     loop.
3. **Clean up.** Remove the file and drop the entry.

A finished task is reaped on the next pass, so reaping can lag by up to one
`poll`. Tasks started in `once` mode are reaped only by the next
`guard_wait` call or by `guard_exit`.

Within one controller, only one task per id exists at a time. That holds
for tasks, not necessarily their children:
- If only a task subshell is SIGKILLed, its `collect.sh` child can survive
  as an orphan. The exit pass can then collect the same id alongside it.
- An orphaned task of a SIGKILLed controller can overlap the next
  controller's task for the same id, as today's single orphaned retirement
  can. Its status file carries the old token and is never read.

In both cases integrity holds: the per-file `flock`, the SHA-gated replace
and the per-worker deletion lock all still apply.

`kill -0` can in theory be fooled by PID reuse, for a task that died without
a status file. The effect would be a reap delayed for as long as the
reused pid's process lives, never a wrong status: the status always comes
from the token file or from `wait`.

### `guard_wait`

- Each pass begins with `guard_retire_reap`; a failure sets `wait_status=1`.
- **All three per-worker loops skip in-flight ids:**
  - the start/probe loop;
  - the probe-wait loop;
  - the classification loop.

  In the first loop, the skip comes **before** the `.retired` and `.deleted`
  checks. Otherwise a task that has just deleted its worker would drop
  `pending` while it is still in flight. A worker with an in-flight task sets
  `pending=1`, so a stale `.ok` or `.reply` can never start a second task.
- **Both return points also require an empty `guard_retiring`.** These are
  the early "nothing pending" return after the first loop, and the
  end-of-pass return.
- Each former inline retirement becomes a start:

  | Path | Old inline action | New start | Status |
  |---|---|---|---|
  | `.deletion-attempted` | `guard_retire` | `retire` | reap failure sets `wait_status=1` |
  | STARTUP_FAILED | `guard_retire \|\| true` | `retire` | `wait_status=1` set as before |
  | DONE | `factory_auto_resume` (inline, unchanged), else `guard_retire` | deferred to phase 2: inline auto-resume, else `retire` (no candidate: `retire` at once) | reap failure sets `wait_status=1` |
  | stall / unreachable / TTL margin | (`factory_ttl_retire` +) `guard_retire \|\| true` | `ttl` for the TTL margin, else `retire` | `wait_status=1` set as before |

  For STARTUP_FAILED, stall, unreachable and the TTL margin, reaping a
  failure adds nothing, because the status is already 1.
- Phase 2 (the deferred list, `guard_deferred`) runs right after the
  classification loop, **before** the `once` return.
- `once` mode returns after one pass without joining. Its tasks keep running
  and a later `guard_wait` reaps them. A non-`once` call returns only when no
  worker is pending and `guard_retiring` is empty.

### `guard_exit`

1. Kill only jobs that are **not** recorded retirement tasks: probes, the poll
   `sleep`, and the gate-smoke watchdog. The existing kill covers all of
   these. A plain `wait` for every job would instead hang on the
   `tools/run-gate-smoke.sh` 2700 s watchdog.
2. Set `guard_exiting=1`, then join the in-flight tasks with
   `guard_retire_reap block`. This happens before `guard_ids resolve`.
   Failures from this join are **logged only**. The exit pass's own result
   decides `cleanup_failed`, as today: an interrupted foreground retirement
   was never counted, and `factory/restore_bundle.py` reads
   `cleanup-status.json`.
3. In the exit pass, start one `retire` task for every id, then join them all
   with `guard_retire_reap block` instead of the sequential loop.
   `guard_retire` replays safely from its `.deleted`, `.collected` and
   `.retiring.json` markers, so a worker its own task already finished is a
   no-op, as today.

Tasks started here inherit ignored INT and TERM, the same as today's exit
pass. The join is longer than systemd's default stop timeout, as today.

For a worker whose collection keeps failing, stop latency can be up to about
twice today's. Its in-flight task finishes its remaining tries (each can
include a pause of up to 1200 s), and then the exit pass makes up to 3 more.
Today, the interrupted foreground collection ends at once. Peers no longer
add their retirement times to each other, though, so for N workers the total
stop latency is lower than today's sequential sum.

### Signals: Ctrl-C and TERM

**Ctrl-C (SIGINT to the process group).**
- An `&` task ignores SIGINT when job control is off.
- `bin/boat-call` installs its own INT handler. So an in-flight `boat-call`
  in a task is interrupted, and its child group is cleaned up, just as
  Ctrl-C interrupts today's foreground collection.
- **An interrupted pause SSH** fails the attempt through `pause_status`.
  `guard_retire`'s own retry then runs (up to 3 tries,
  `BOAT_COLLECT_RETRY_SECONDS` apart).
- **An interrupted transfer chunk** is usually just retried inside
  `transfer.py`.
- Meanwhile the launcher's trap runs `exit 130`, and `guard_exit` joins the
  task before its exit pass.

Today, Ctrl-C aborts the foreground collection and the exit pass collects
again. Afterwards, the outcome is the same as today: an uncollected worker is
never deleted, collection is retried, and a worker that still cannot be
collected is kept with the TTL as the backstop.

**`factory_ttl_retire` inside a `ttl` task.** If Ctrl-C makes its SSH fail,
the existing `|| echo "TTL attestation failed ..."` path logs it, and
collection proceeds without attestation. Today, the trap would skip the
attestation and the exit pass would collect without it. Either way the
result is the same: no continuation is queued, and collection still happens.

**TERM to the launcher only:** the same as above, except the tasks are not
interrupted. A `ttl` task may then complete its attestation, and `collect.sh`
may queue the case as `queued_policy_required` in
`results/ttl-continuations`. That queue only *records* eligibility. A
continuation still needs its own separately admitted launch, so no model
work starts.

**Auto-resume:** inline, so its signal behaviour is unchanged.

**TERM to the whole cgroup (systemd):** everything dies, as today. Replay
markers govern the next controller.

### Concurrency audit (parallel tasks for distinct workers)

- **Shell state.** `retire_id`, `retire_status`, `tries`, `collect_status`
  and `files` are subshell-local. Auto-resume stays in the main shell, as
  today.
- **Collection** (`collect.sh`):
  - `transfer.py` holds a per-file `flock` and replaces a file only after a
    SHA match;
  - `collection.py` verifies only the names its own collection listed;
  - `--restore` and batch operations force `N=1` (`launch.sh`), and fresh
    case ids are timestamp plus random, so the workers of one launch never
    collect the same case name.
- **Bandwidth.** N tasks transfer chunks at the same time, sharing host
  bandwidth under the 120 s-per-8 MiB chunk bound. A contended chunk that
  times out fails the collection attempt. Chunks resume across
  `guard_retire`'s retries, and only SHA-verified bytes replace a result. So
  contention costs retries, never integrity. The live effect at large N is
  unmeasured.
- **Deletion.** `boat_lifecycle.delete_receipt` uses a per-worker
  `<id>.deletion.lock` and a per-worker evidence directory. `boat delete` and
  `hcloud-park` take one id. `guard_ids resolve` replaces `$state/ids`
  atomically, so a once-mode task overlapping `guard_new` reads either the
  old or the new id list, and both contain its own id.
- **Continuation hooks.**
  - `ttl_continuation.py` locks per case (`coordinator.locked`).
  - `batch_holder.py collect` runs only for batch operations, which bind
    exactly one worker per operation (`op['worker_id']`).
  - `factory_auto_resume` returns 1 under `UNBUG_BATCH_OPERATION`.
- **`bin/exam-launch`.** Its `collect_vm` uses the sh globals `files`,
  `collect_status` and `dest`. They are safe only because each task is a
  subshell. It uses per-file `scp`, and the launch is `n=1`.

## What it deletes

The sequential exit loop and the inline retirement work in `guard_wait`'s
classification loop. Both become start/reap pairs. No new retirement path is
added, and `guard_retire`, `factory_ttl_retire` and `factory_auto_resume`
themselves are unchanged.

## Out of scope (why row 16 stays open)

- **The reserve is shorter than sealing.** On SIGTERM, `run.py` seals a
  checkpoint: encryption up to 600 s (`factory/run_artifacts.py`), then the
  R2 PUT up to 1800 s (`factory/r2_upload.py`). DONE can arrive about 2400 s
  after the pause request. That is longer than both the 1050 s pause wait and
  the 1800 s margin.
  - Fixing it means bounding the worker-side seal and upload by the remaining
    provider lifetime, or checkpointing earlier.
  - That touches worker release code, the row-34 files (`r2_upload.py` and
    `durable_checkpoint.py`, owned elsewhere) and practice timing
    (`practice.TIMING`: `retire_at == 1800`, `ttl == 3600`, frozen by the
    practice4 branch).
  - It also needs live timing proof.
- **Some retirement-related work stays synchronous in `factory/launch.sh`.**
  It runs in the creation loop or the poll loop, so earlier peers can be due
  meanwhile and are delayed by it. It is left unchanged to keep the diff
  small and stop semantics identical.
  - **The setup-failure `guard_retire`.** Its impact is low: a setup-failed
    worker has no `run.py` to pause, so its collection is short.
  - **The `guard_retire` after a failed `guard_new`.**
  - **Inline `factory_auto_resume` for DONE factory workers.** Same-pass
    peers are not affected, because of the two phases. A peer that only
    becomes due on a **later** pass waits for that pass, so behind the
    in-progress inline auto-resumes.
    - Its `collect_vm` runs on a worker that already wrote DONE, so
      `collect.sh` skips the 1050 s pause.
    - The worst-case bound per auto-resume is the chunked transfer of the
      sealed checkpoint, plus a few SSH calls of up to 120 s each and the
      local planners. Each 8 MiB chunk is bounded at 120 s and retried 3
      times (`COLLECT_CHUNK_RETRIES`), so up to 360 s per chunk. A ~500 MiB
      archive is about 63 chunks, or about 6.3 h if every chunk ran to its
      bound. `metadata()` calls and a `flock` wait on the same name come on
      top. Several DONE
      workers in one pass run their auto-resumes in turn, as today.
    - A typical transfer takes minutes, but the worst case is the bound
      above.
    - Moving auto-resume out of the main shell needs its own stop design;
      design review 2 explains why.
- **No live proof.** The transports are authored. Real archive ciphertext is
  never saved in the repo.

## Cost, risk and impact

- **Cost:** one shell file, about 60 changed lines, plus one test file. No
  money, routes or timing values change.
- **Timeline:** a single change on this branch. Nothing rolls out until root
  re-pins the launcher fingerprint and deploys. Live proof needs a separately
  authorised multi-worker launch.
- **Risk:** a new background process model in the launcher. This is
  mitigated by signal deferral, token-named status files, the liveness
  fallback, treating death as failure, and tests under both dash and
  `bash --posix`.
- **Impact:** with N workers due for retirement in the same pass, the k-th
  worker's collection starts at once, instead of after k-1 earlier
  retirements (each up to about 20 minutes or more). A worker due on a later
  pass starts within one `poll` of becoming due, plus any inline
  auto-resumes running in that pass (see Out of scope). It does not make a single worker's seal fit the
  reserve: that is the open half of row 16. So it saves the queued workers
  whose own seal fits the 1800 s reserve. That covers, for example, a stopped
  or idle case with a small checkpoint, and any worker retired for DONE,
  stall or unreachable.

## Tests

New file `tests/bench/test-independent-retirement.py`.

- **What it drives:** the real `guard_wait`/`guard_exit` in
  `bin/boat-launch-guards.sh`, through the real `bin/boat-call`, with an
  authored `BOAT_CMD` transport.
- **Timing:** `ttl_seconds` and `retire_at` come from the real saved launch
  layout `tests/factory/fixtures/isolation-timeouts/monitor.json`. Its floats
  are converted with `int()`, and `margin = ttl_seconds - retire_at` is
  checked. The fixture's real worker id `bx_d6dzvjbc` is one of the ids.
- **Shells:** each scenario runs under `/bin/sh` (dash here) and under
  `bash --posix` when bash exists.
- **Determinism:** barriers are files with bounded waits, so the tests are
  event-driven and do not depend on timing.
- **Harness:**
  - The script sources the real guard and sets the `guard_init` outputs
    directly. `ttl_seconds` and `retire_at` come from the fixture; `poll`,
    `stall_seconds` and `unreachable` are small test values, which are not
    under test. `guard_init` itself is not run: it needs `boat-spend --check`,
    and the existing guard tests already cover it.
  - The exit trap and the `exit 130`/`exit 143` traps are installed exactly
    as `guard_init` installs them.
  - Signals:
    - INT goes to the whole group, via `start_new_session=True` and
      `os.killpg`;
    - TERM goes to the launcher pid only.
  - **Concurrent collections of one id** are detected by the stub's
    `mkdir "$state/$id.collecting"` lock. A failed `mkdir` records an
    `overlap` event, which the tests assert never happens.
- **Mutation check:** run with `GUARD=<base guard>`. The expected failing
  assertions are scenario 1's overlap barrier (`not all collections
  overlapped`) and scenario 3's two-phase barrier.

Scenarios:

1. **Simultaneous TTL margin.** Three workers have been running for
   `retire_at` seconds. A stub `collect_vm` blocks until all three have
   started, bounded at 20 s. Pass: all three collections overlap;
   `factory_ttl_retire` runs inside each task, before collection; all three
   are deleted and `.retired`.
   - **Mutation check (manual, recorded in the diff review):** run the same
     test file with `GUARD=<base guard>`, where the base copy comes from
     `git show origin/factory-simplify:bin/boat-launch-guards.sh`. It must
     fail.
2. **A later-due worker is not queued, and failure stays isolated.** Worker
   A's collection blocks until worker B is deleted. B becomes DONE on a later
   poll. Pass: B is retired while A is in flight, and `guard_wait` returns
   only after both. In a variant, A's collection fails all three tries. Pass:
   `guard_wait` returns 1, A is kept (not deleted), and B is still deleted.
3. **`once` does not join, and auto-resume is deferred and stays inline.**
   - `guard_wait once` returns while A's collection is blocked, and a later
     `guard_wait` reaps A.
   - **Two phases.** Within one pass, DONE factory worker D (an auto-resume
     candidate) sorts **before** TTL-due worker T. The stub
     `factory_auto_resume` for D blocks until T's collection has started,
     bounded at 20 s. Pass: T's task started before D's inline auto-resume
     ran. On the base guard the barrier times out.
   - **Auto-resume outcomes.** An inline `factory_auto_resume` that returns 0
     leaves the worker pending, with no task and no `.retired`. When it later
     returns 1, a `retire` task starts.
4. **Liveness: death is failure.**
   - A task killed with SIGKILL writes no status file. Its stub finds the
     task's own pid as the `$PPID` of a child `sh -c 'echo $PPID'`, because
     `$$` inside the task is the controller's pid.
   - Pass: the task is reaped and its worker is `.retired`.
   - Pass: the worker is not probed or collected again by `guard_wait`, and
     `guard_wait` returns 1 rather than hanging.
   - Pass: a stale `.retirement-exit.*` file left before start is ignored.
5. **Exit trap joins rather than kills.**
   - **TERM to the launcher shell** while A's collection is blocked. Pass:
     A's single collection completes, A is deleted exactly once, a peer still
     due at exit is retired in the exit pass, and the exit status is 143.
   - **INT to the whole process group** while A's pause SSH is blocked inside
     `boat-call`. The stub `collect_vm` calls the real `bin/boat-call ssh`,
     and the authored transport blocks the first call. Pass: the interrupted
     attempt fails, `guard_retire` retries, there are never two concurrent
     collections of A, A is deleted exactly once, and the exit status is 130.
   - **The signal window is not tested.** It holds only builtins, so a
     signal from Python cannot land in it deterministically. The deferral is
     argued from shell semantics (design reviews 3 and 4) and was checked
     with a dash experiment. It is not counted as test proof.
   - **Signal during inline auto-resume while a peer task is in flight.**
     TERM arrives while the stub `factory_auto_resume` runs. Pass: the trap
     fires between its commands (the stub's next command never runs),
     `guard_exit` joins the peer task, and the exit status is 143.
6. **Real `collect.sh`.** Two DONE workers have authored remote `sealed/`
   directories (an authored card whose `sha256` binds an opaque archive). The
   real `factory/collect.sh`, `transfer.py` and `collection.py` collect them
   concurrently into one destination through an authored transport. Pass:
   both are verified and deleted. The card is authored, so this scenario is
   **not** real-artifact evidence for closing row 16.

A once-mode task overlapping `guard_new` and `guard_ids resolve` is not
tested separately. Two things cover it instead:
- `guard_ids resolve` replaces `ids` atomically. Its write path is unchanged,
  and the existing launcher tests cover it.
- The only task-side reader of `ids` is `_delete`'s ownership check, which
  only needs the task's own id. That id is present in both the old and the
  new list.
7. **No regression.** These still pass:
   - `tests/bench/test-launch-guards.py` (factory and exam paths);
   - `tests/bench/test-guard-bounds.py`;
   - `tests/factory/test_ttl_continuation.py`;
   - `tests/factory/test_boat_settlement.py`;
   - `tests/factory/test_control_resume.py`;
   - `tests/factory/test_admission_handoff.py`;
   - `tests/tools/test_gate_smoke.py`.

## Murphy rows

- **Row 16:** works towards it, but does not close it. Independent
  retirement is offline-proved with authored transports. The
  reserve-versus-sealing bound and the live multi-worker retirement remain.
- No new row: no new real-run failure was observed.

## Deployment note

`bin/boat-launch-guards.sh` is in `launch_manifest.TRUSTED_FILES`, so the
holder/launcher fingerprint changes. Root owns the re-pin. Nothing is deployed
from this branch.
