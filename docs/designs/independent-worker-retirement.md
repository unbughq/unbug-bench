# Independent per-worker retirement

Murphy row 16, partial: the queueing half only. The row stays **open**.

## Problem

`bin/boat-launch-guards.sh` retires workers one after another.

- In `guard_wait`, a single loop walks every worker of a multi-worker launch
  (`factory/launch.sh N`). When a worker is due (DONE, startup failure, stall,
  unreachable, or the TTL margin), the loop calls `guard_retire` inline and
  only then moves to the next worker.
- `guard_exit` (the exit trap, on any exit, INT or TERM) does the same:
  `for exit_id in $(cat "$state/ids"); do guard_retire ...; done`.
- `guard_retire` is slow by design. `collect_vm` (`factory/collect.sh`) first
  asks a running case to pause. That SSH is bounded by
  `COLLECT_PAUSE_SECONDS` (1200 s), and the pause waits up to 105 × 10 s =
  1050 s for DONE. Chunked transfers follow. A failed collection is retried up
  to 3 times, 30 s apart, so one retirement can take about an hour.
- Workers in one launch are created within minutes of each other, with the
  same TTL (`ttl_seconds`) and the same `retire_at`. They therefore reach the
  TTL margin (`margin`, default 1800 s) in the same poll. Worker k starts
  collection only after workers 1..k-1 finish. Real launch layout
  `tests/factory/fixtures/isolation-timeouts/monitor.json` has
  `margin=1800`, `ttl_seconds=57600` and `retire_at=55800`. With two or more
  workers, the second worker's 1800 s reserve is already spent by the first
  worker's pause, and Boat's TTL erases it (`--no-snapshots`) unsnapshotted.
- `guard_wait once` runs between worker creations in `factory/launch.sh`. A
  synchronous retirement there also stalls provisioning of the next worker.
- A worker that becomes due on a later poll waits behind any retirement still
  in progress, because the loop does not poll again until it returns.

## Change

Each due worker gets its own background retirement task. The poll loop never
blocks on a retirement.

1. **New `guard_retire_start <id>`.**
   - Removes any stale `<id>.retirement-exit` file.
   - Runs `( trap - 0; s=0; guard_retire "$id" || s=$?; echo "$s" > tmp; mv tmp "$state/$id.retirement-exit" ) &`.
   - Records `id:pid` in the shell variable `guard_retiring`.
   - `trap - 0` makes sure the subshell can never run `guard_exit`.
   - `|| s=$?` keeps `guard_retire` out of `set -e`, exactly as the old
     `guard_retire ... || ...` call sites did.
2. **New `guard_retire_reap [block]`.** For each in-flight task whose
   `<id>.retirement-exit` exists (or every task, with `block`), it:
   - `wait`s its pid;
   - reads the status (a missing or invalid status counts as a failure);
   - touches `<id>.retired`;
   - removes the exit file and drops the task from `guard_retiring`.
   It returns 1 if any reaped retirement failed.
3. **`guard_wait`.**
   - Every place that called `guard_retire "$wait_id"` and then touched
     `.retired` now calls `guard_retire_start`. That covers the
     deletion-attempted receipt path, STARTUP_FAILED, DONE, and
     stall/unreachable/TTL margin.
   - A worker with an in-flight task is neither probed nor started again.
   - Each pass first reaps finished tasks. The loop stays `pending` while any
     task is in flight.
   - `once` mode returns without joining. Its tasks keep running and are
     reaped by a later call.
   - Non-`once` `guard_wait` returns only when no worker is pending and no
     task is in flight. Then it joins (`guard_retire_reap block`, a no-op at
     that point).
   - Status is unchanged. Retirement after DONE, or of a recorded deletion,
     returns 1 only if retirement fails. The other paths already set
     `wait_status=1`.
4. **`guard_exit`.**
   - It no longer `kill -TERM`s in-flight retirement tasks. It kills only the
     other jobs (probes, the poll `sleep`).
   - Then it joins the retirement tasks. Killing a task would orphan its
     `collect.sh`, and the exit pass would then collect the same worker
     concurrently.
   - The exit pass starts a task for every remaining id and joins them all,
     instead of a sequential loop.
   - `guard_retire` is already replay-safe: `.deleted`, `.collected` and
     `.retiring.json` markers. So a worker whose task already finished is a
     no-op, as today.

### Concurrency audit (why parallel `guard_retire` is safe)

- **Shell state:** `retire_id`, `retire_status`, `tries`, `collect_status` and
  `files` are subshell-local.
- **Collection** (`collect.sh`):
  - `transfer.py` holds a per-file `flock` and only replaces after a SHA
    match;
  - `collection.py` verifies only the names its own collection listed;
  - workers of one launch run distinct cases.
- **Deletion:** `boat_lifecycle.delete_receipt` uses a per-worker
  `<id>.deletion.lock` and a per-worker evidence directory. `boat delete` and
  `hcloud-park` take one id.
- **Continuation hooks:** `ttl_continuation.py` uses `coordinator.locked`
  (blocking `LOCK_EX`). `batch_holder.py collect` runs only for batch
  operations, which bind exactly one worker per operation (`op['worker_id']`).
  So no two tasks of one launch reach it.
- **Signals:** with job control off, `&` tasks ignore SIGINT, as POSIX
  specifies. Ctrl-C therefore lets an in-flight collection finish, and
  `guard_exit` joins it. systemd TERM to the cgroup kills everything, as it
  does today. Replay markers then govern the next controller.
- **Restart** (`UNBUG_RESUME_LAUNCH`): `guard_retiring` starts empty. A stale
  `.retirement-exit` from a crashed controller is never read, because only ids
  in `guard_retiring` are reaped, and `guard_retire_start` deletes it first. A
  worker without `.retired` is probed and retired again, as today.
- **New state-dir file `<id>.retirement-exit`:**
  - it is removed on reap;
  - no reader globs it (`*.retiring.json` is a different name);
  - `deployment_inventory` only counts unknown entries.

## What it deletes

Nothing is removed, apart from the two sequential `guard_retire` loops. Each
becomes a start/reap pair. No new retirement path is added; `guard_retire` is
unchanged.

## Out of scope (why row 16 stays open)

- **The reserve is shorter than sealing.** On SIGTERM, `run.py` seals a
  checkpoint: encryption up to 600 s (`factory/run_artifacts.py`), then the
  R2 PUT up to 1800 s (`factory/r2_upload.py`). DONE can arrive about 2400 s
  after the pause request. That is longer than both the 1050 s pause wait and
  the 1800 s margin.
  - Fixing it means bounding the worker-side seal and upload by the remaining
    provider lifetime, or checkpointing earlier.
  - That touches worker release code, the row-34 files
    (`r2_upload.py`/`durable_checkpoint.py`, owned elsewhere) and practice
    timing (`practice.TIMING`: `retire_at == 1800`, `ttl == 3600`, frozen by
    the practice4 branch).
  - It also needs live timing proof.
- **Some retirements stay synchronous:** the per-setup-failure
  `guard_retire` in `factory/launch.sh`, and `collect_vm` inside
  `factory_auto_resume`. Each runs before any peer is due from the same
  creation step, and changing them is not needed for this piece.
- **No live proof:** collection uses authored transports. Real archive
  ciphertext is never saved in the repo, so the real `collect.sh` cannot
  verify a real card offline.

## Tests

New file `tests/bench/test-independent-retirement.py`. It drives the real
`guard_wait`/`guard_exit` from `bin/boat-launch-guards.sh` through
`bin/boat-call`, with an authored `BOAT_CMD` transport and an authored
`collect_vm` seam. Timing values come from the real saved launch layout
`tests/factory/fixtures/isolation-timeouts/monitor.json` (`ttl_seconds`,
`margin`, `retire_at`). Its real worker id `bx_d6dzvjbc` is one of the ids.
The tests are event-driven (barriers), not timing-sensitive.

1. **Simultaneous TTL margin.** Three workers started `retire_at` seconds ago
   are all due in one poll. Each `collect_vm` blocks until all three have
   started, bounded at 60 s. Pass: all three collections overlap, and all
   three are deleted and `.retired`. On the old sequential code the barrier
   times out. The test is run against the base guard to confirm it fails
   there.
2. **A later-due worker is not queued.** Worker A is due and its collection
   blocks until worker B has been deleted. B becomes DONE on a later poll.
   Pass: B is retired while A is in flight. A is then retired, and
   `guard_wait` returns only after both. Also: A's retirement failing (all
   three collection tries fail, so the VM is kept) gives `guard_wait` status
   1, B is still deleted and A is not deleted.
3. **`once` does not join.** `guard_wait once` returns while A's collection is
   blocked. A later `guard_wait` reaps it.
4. **Exit trap joins rather than kills.** TERM reaches the launcher shell
   while A's collection is blocked. Pass: A's `collect_vm` runs to completion
   exactly once, with no overlapping second collection for A. A is deleted
   exactly once, and the exit status is 143.
5. **No regression.** The existing guard tests still pass:
   `tests/bench/test-launch-guards.py`, `tests/bench/test-guard-bounds.py`,
   `tests/factory/test_ttl_continuation.py`,
   `tests/factory/test_boat_settlement.py` and
   `tests/factory/test_control_resume.py`.

## Murphy rows

- **Row 16:** works towards it, but does not close it. Independent retirement
  is offline-proved with an authored transport. The reserve-versus-sealing
  bound and the live multi-worker retirement remain.
- No new row: no new real-run failure was observed.

## Deployment note

`bin/boat-launch-guards.sh` is in `launch_manifest.TRUSTED_FILES`, so the
holder/launcher fingerprint changes. Root owns the re-pin. Nothing is deployed
from this branch.
