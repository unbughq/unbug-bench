# Independent per-worker retirement

Murphy row 16, partial: the queueing half only. The row stays **open**.

Revision 2 addresses `docs/reviews/independent-worker-retirement-design-1.md`.

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

Every per-worker action that `guard_wait` used to run inline after
classifying a worker now runs in that worker's own background task:
`factory_ttl_retire`, `factory_auto_resume`, `guard_retire` and the
`.retired` decision. The poll loop does only probes (bounded by the Boat
command timeout), classification, task starts and reaping.

### `guard_retire_start <id> <kind>`

`kind` is one of:
- `retire`: plain `guard_retire`;
- `ttl`: `factory_ttl_retire` if it is defined (a failure only logs, as
  today), then `guard_retire`;
- `done`: `factory_auto_resume` if it is defined and `label=factory`. If it
  returns 0, the outcome is `resumed`. Otherwise run `guard_retire`.

Steps:
1. Bump a counter, then set `gr_token=$$.$counter` and
   `gr_exit=$state/$id.retirement-exit.$gr_token`.
2. Unless `guard_exiting` is set, install deferring traps:
   `trap 'gr_signal=130' INT` and `trap 'gr_signal=143' TERM`.
3. Start the task:
   ```sh
   ( trap - 0
     gr_s=0; <kind work> || gr_s=$?
     printf '%s\n' "$gr_s" > "$gr_exit.tmp" && mv "$gr_exit.tmp" "$gr_exit" ) &
   ```
   For `resumed`, the task writes the word `resumed`.
4. Append `id:pid:token` to the space-separated shell variable
   `guard_retiring`.
5. Restore `trap 'exit 130' INT` and `trap 'exit 143' TERM`. If `gr_signal`
   was set, run `exit "$gr_signal"`.

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
   - **`resumed`:** do not touch `.retired`. The worker returns to polling,
     exactly as when `factory_auto_resume` returned 0 inline.
   - **Missing or invalid status:** the task died. Log it, set the return
     value to 1 and do **not** touch `.retired`, so that a later poll probes
     the worker again and `guard_retire` replays from its markers. Only one
     task per id can exist at a time, so this cannot produce a concurrent
     duplicate.
3. **Clean up.** Remove the file and drop the entry.

### `guard_wait`

- Each pass begins with `guard_retire_reap`; a failure sets `wait_status=1`.
- **All three per-worker loops skip in-flight ids:**
  - the start/probe loop;
  - the probe-wait loop;
  - the classification loop.
  
  A worker with an in-flight task keeps `pending=1`, so a stale `.ok` or
  `.reply` can never start a second task.
- Each former inline action becomes a start:

  | Path | Old inline action | New start | Status |
  |---|---|---|---|
  | `.deletion-attempted` | `guard_retire` | `retire` | unchanged |
  | STARTUP_FAILED | `guard_retire \|\| true` | `retire` | `wait_status=1` set as before |
  | DONE | `factory_auto_resume`, else `guard_retire` | `done` | reap failure sets `wait_status=1` |
  | stall / unreachable / TTL margin | (`factory_ttl_retire` +) `guard_retire \|\| true` | `ttl` for the TTL margin, else `retire` | `wait_status=1` set as before |

  For STARTUP_FAILED, stall, unreachable and the TTL margin, reaping a
  failure adds nothing, because the status is already 1.
- `once` mode returns after one pass without joining. Its tasks keep running
  and a later `guard_wait` reaps them. A non-`once` call returns only when no
  worker is pending and `guard_retiring` is empty.

### `guard_exit`

1. Kill only jobs that are **not** recorded retirement tasks: probes, the poll
   `sleep`, and the gate-smoke watchdog. The existing kill covers all of
   these. A plain `wait` for every job would instead hang on the
   `tools/run-gate-smoke.sh` 2700 s watchdog.
2. Set `guard_exiting=1`, then join the in-flight tasks with
   `guard_retire_reap block`. Their failures make the cleanup fail, through
   `guard_cleanup_error`.
3. In the exit pass, start one `retire` task for every id, then join them all
   with `guard_retire_reap block` instead of the sequential loop.
   `guard_retire` replays safely from its `.deleted`, `.collected` and
   `.retiring.json` markers, so a worker its own task already finished is a
   no-op, as today.

Tasks started here inherit ignored INT and TERM, the same as today's exit
pass. The join can last as long as today's sequential pass (about an hour per
worker). That is longer than systemd's default stop timeout, as today.

### Signals: Ctrl-C and TERM

**Ctrl-C (SIGINT to the process group).**
- An `&` task ignores SIGINT when job control is off.
- `bin/boat-call` installs its own INT handler. So an in-flight pause SSH or
  transfer in a task is interrupted, and its child group is cleaned up, just
  as Ctrl-C interrupts today's foreground collection.
- The task's `collect_vm` then fails, and `guard_retire`'s own retry runs (up
  to 3 tries, `BOAT_COLLECT_RETRY_SECONDS` apart).
- Meanwhile the launcher's trap runs `exit 130`, and `guard_exit` joins the
  task before its exit pass.

Today, Ctrl-C aborts the foreground collection and the exit pass collects
again. Afterwards, the outcome is the same as today: an uncollected worker is
never deleted, collection is retried, and a worker that still cannot be
collected is kept with the TTL as the backstop. One overlap is removed:
today's exit pass and an orphaned `collect.sh` could collect one worker
concurrently. Now each id has exactly one task at a time.

**TERM to the launcher only:** the same as above, except the tasks are not
interrupted.

**TERM to the whole cgroup (systemd):** everything dies, as today. Replay
markers govern the next controller.

### Concurrency audit (parallel tasks for distinct workers)

- **Shell state.** `retire_id`, `retire_status`, `tries`, `collect_status`,
  `files` and `factory_auto_resume`'s `resume_id`, `remaining`, `attempts` and
  `restart_plan` are subshell-local. `factory_auto_resume` sets no main-shell
  variable that the poll loop reads afterwards. Its side effects are all state
  files keyed by worker id.
- **Collection** (`collect.sh`):
  - `transfer.py` holds a per-file `flock` and replaces a file only after a
    SHA match;
  - `collection.py` verifies only the names its own collection listed;
  - case ids are timestamp plus random, so the workers of one launch run
    distinct cases.
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
- **`bin/exam-launch`.** Its `collect_vm` uses only function-local variables
  and per-file `scp`. It launches `n=1`.

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
- **The setup-failure `guard_retire` in `factory/launch.sh` stays
  synchronous.** It runs in the creation loop, so earlier peers can be due
  meanwhile and are delayed by it. The impact is low: a setup-failed worker
  has no `run.py` to pause, so its collection is short. It is left
  unchanged to keep the diff small.
- **No live proof.** The transports are authored. Real archive ciphertext is
  never saved in the repo.

## Cost, risk and impact

- **Cost:** one shell file, about 60 changed lines, plus one test file. No
  money, routes or timing values change.
- **Risk:** a new background process model in the launcher. This is
  mitigated by signal deferral, token-named status files, the liveness
  fallback, and tests under both dash and `bash --posix`.
- **Impact:** with N workers due together, the k-th worker's collection
  starts about at once instead of after k-1 earlier retirements (each up to
  about 20 minutes or more). It does not make a single worker's seal fit the
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

Scenarios:

1. **Simultaneous TTL margin.** Three workers have been running for
   `retire_at` seconds. A stub `collect_vm` blocks until all three have
   started, bounded at 60 s. Pass: all three collections overlap;
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
3. **`once` does not join, and auto-resume runs in the task.** `guard_wait
   once` returns while A's collection is blocked, and a later `guard_wait`
   reaps A. In a separate case, a `factory_auto_resume` that returns 0 leaves
   the worker pending without `.retired`, and it is retired on a later DONE.
4. **Liveness.** A task killed with SIGKILL, so it writes no status file, is
   reaped. Its worker is not `.retired`. It is probed again, retired on the
   next pass, and `guard_wait` returns 1 rather than hanging. A stale
   `.retirement-exit.*` file left before start is ignored.
5. **Exit trap joins rather than kills.**
   - **TERM to the launcher shell** while A's collection is blocked. Pass:
     A's single collection completes, A is deleted exactly once, a peer still
     due at exit is retired in the exit pass, and the exit status is 143.
   - **INT to the whole process group** while A's pause SSH is blocked inside
     `boat-call`. Pass: the interrupted attempt fails, `guard_retire` retries,
     there are never two concurrent collections of A, A is deleted exactly
     once, and the exit status is 130.
   - **Signal window:** the trap-deferral code path runs with a signal sent
     right after the task starts. Pass: the task is recorded and joined, not
     killed.
6. **Real `collect.sh`.** Two DONE workers have authored remote `sealed/`
   directories (an authored card whose `sha256` binds an opaque archive). The
   real `factory/collect.sh`, `transfer.py` and `collection.py` collect them
   concurrently into one destination through an authored transport. Pass:
   both are verified and deleted.
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
