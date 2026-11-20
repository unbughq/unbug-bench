# Never lose a live worker on one bad inventory read (2026-11-20)

Founder, 2026-11-20 ~10:40 UTC: "Let's fix them".

## Problem

- `Executor.run` declared an attempt `infra:worker_lost` the first time `pool.alive(lease)` answered False, even
  while the worker was answering polls. The same single read decided `_cancel_confirm` and `reconcile`.
- `alive` is one `boat list` (`workers.py` `alive` / `_inventory` / `_find`). On 11-20 08:50 (cb5e26 G10), on
  11-19 (cb5e26) and on 11-20 01:52 (1108c), one read missed a live box. The next pool lookup found the same box.
- The lost result settles the whole grant as phantom waste (`settle_lost`). The retry then cancels or collides with
  the orphan: the worker refuses the new start with `infra:attempt_busy`, which counts as infra. Once the allowance
  is used up, the diagnosis is refused busy too, `diagnosis_infra_holds` holds the case, and `finish` →
  `release_step` deletes the box while the G10 is still running on it.

## Change

1. **Executor (`_Presence`, `policy.LOST_MISSES = 3`, `LOST_WINDOW_S = 120`).** A worker is gone only when it has
   stopped answering and the inventory has missed it 3 times in a row, the misses spanning at least 120 s. In
   detail:
   - A poll the worker answers (RUNNING, ABSENT or DONE) proves it alive. It resets the count, and no inventory
     read is made at all.
   - Otherwise each round asks the pool. A miss counts. A find resets the count.
   - Gone means 3 consecutive misses whose span is at least 120 s, with no poll answered since the first miss.
   - The same tracker serves `run` (the main loop, the ABSENT branch and the past-deadline branch), the
     `_cancel_confirm` it calls, and `reconcile`.
   - `Executor.cancel` keeps one read. It is the final cancel of a prior attempt whose result is already
     settled, before a retry starts, and its worker is most often one the engine itself released (a credit park
     or a pause). Two minutes there would delay every such retry. A live leftover there is caught by the start's
     `attempt_busy` wait (2).
   - `Executor(lost_window_s=...)` is the window, so the engine fakes can run at fake speed (0.05 s). Production
     uses the policy value.
   - `pool.alive` also answers False without a read when the case has no record, or the record names another
     worker. That is definite, but `_Presence` waits out its window on it too. It costs about two minutes, only
     for a box the pool no longer claims.
   - Why N = 3 over 120 s:
     - All three observed blips were one read, and the very next read found the box.
     - Three in a row, spread over two minutes, while the worker also fails every poll, is not a blip.
     - At the 30 s production poll a dead box is called gone after misses at 0, 30, 60, 90 and 120 s, so 2 to 2.5
       minutes after death. The old figure was one round. That is still "a few minutes".
     - A slow poll (an SSH timeout) only spreads the misses further apart, so 3 misses suffice once they span
       120 s.
   - Unchanged:
     - the silent-and-unrenewed retirement (`SILENT_WORKER_LIMIT_S`);
     - the unconfirmed limit (`_retire` after deadline + `UNCONFIRMED_WORKER_LIMIT_S`);
     - "unknown is not gone" (an unreadable inventory is alive).
2. **Engine (`attempt_busy_waits` patch).** A start refused `infra:attempt_busy` proves that the box is alive and
   still running an earlier attempt of this case (`worker_step.busy`). Under the new DBOS patch:
   - It waits like a worker-pool outage (`pool_wait`). It naps `pause_retry_s` on the same worker. It is never
     counted against `max_infra_retries_per_step`, so it never reaches a diagnosis or the hold that deletes the
     box.
   - The RETRY wait never releases the worker for a busy result, even when a batch sets a short
     `release_worker_after_sleep_s`.
   - The wait is bounded by the longest attempt deadline plus grace: `max(step_deadline_s, GATES_DEADLINE_S) +
     POLL_GRACE_S` (12 h 15 min), not the 6 h `pool_wait_ceiling_s`, which is shorter than a GATES attempt. The
     worker kills the orphan at its own `deadline_s`, so the box stops being busy by then. Past that bound it
     counts as infra as before.
   - Each busy retry still goes through `acquire`, which reads the inventory once. If that one read misses the
     box, `acquire` moves the case to a fresh box, and the orphan's box becomes a stray that `sweep` deletes. The
     orphan's result was never going to be collected (its attempt was settled lost), so nothing the engine uses
     is lost: the step restarts sooner on a fresh box. Making `acquire` wait on a miss would leave a case stuck on a
     truly dead box, so it is not changed.
3. **Controller restart (`BoatPool.recover`).** On start, `recover` dropped a case's record when its worker was
   missing from its one inventory read, and the next `sweep` (within 300 s) deleted the box as a stray, under the
   attempt the restarted controller reattaches. Now a record whose worker is merely missing from the list is kept:
   - `acquire` replaces it if the box is really gone;
   - the reattached attempt calls the worker lost only through `_Presence`;
   - `sweep` has no row to delete.
   A row that is present but not ours to adopt (dead, or mismatched) is still deleted, as before: that is an
   observation, not a miss. This matters because this change's own deploy is a controller restart.
   - Workflows recorded before the patch replay their old path (a counted infra error), so no recorded history
     diverges.

## What it deletes

The executor's per-round `boat list` while the worker answers. The single-read loss path is replaced, not guarded.

## Tests

- `tests/factory/test_durable_engine_executor.py::InventoryMiss`, with the executor's real code and its fake seams
  (the existing executor test style):
  - One miss while the worker answers RUNNING, then DONE: OK, with 0 inventory reads and no release. Also an
    inventory that never matches the record while the worker answers.
  - Isolated misses while polls also fail (misses on reads 1, 3, 5, 7), or two misses and then a find: OK.
  - A dead box (inventory empty, polls failing) is still `infra:worker_lost`, with its checkpoint, after 120 to
    180 s at a 30 s poll, and after exactly 3 misses (180 s) at a 90 s poll.
  - `reconcile` rides out a one-read blip and confirms the cancel.
  - `test_a_dead_worker_needs_no_cancel` is unchanged: `cancel` keeps one read.
- `tests/factory/test_durable_engine.py::Outcomes.test_a_busy_worker_is_waited_for_on_the_same_box_never_counted_diagnosed_or_released`,
  through the real engine and DBOS:
  - Four busy GATES attempts with an infra allowance of 1 and a pool ceiling of 0.1 s: the case seals, every
    attempt is on the same worker, and no release happens before the end.
  - With the patch disabled (a recorded workflow), the old path ends in a diagnosis.
- `tests/factory/test_durable_workers.py::PoolTests.test_restart_keeps_a_recorded_worker_that_one_list_missed`,
  on the real saved `boat list` envelope (`isolation-timeouts/list.json`) with the box missing from one read: the
  restart keeps the record, the next sweep deletes nothing, and the box is alive and leased again.
- Failing first: with the executor and policy reverted, all 4 `InventoryMiss` tests fail (5 failures: one test
  fails in both subtests). With `recover` reverted, the restart test fails. The busy engine test's
  disabled-patch arm is the old path, and it ends in a diagnosis.
- The engine fakes' worker reported busy across boxes (one per-case list). The real `worker_step.busy` reads the
  box's own case directory, so a fresh box is never busy. The fake now scopes busy to the box too. With the busy
  wait, the cross-box fake had made `test_failure_drill.py`'s deleted-worker drill nap 900 s on a fresh box.
- The engine fakes' worker now answers a dead or dropped poll with the contract's shared `UNANSWERED`, as
  `channel.BoatChannel` does (`RUNNING = UNANSWERED`). It used to return a fresh `Poll(RUNNING)`, which the executor
  reads as an answer, so a released fake worker would have looked alive forever.
- Real-artifact gap: no `boat list` output from 08:50 is in the repo, so the blip is reproduced at the seam
  (`pool.alive`). The fix does not depend on why the read missed: a box that answers is never lost, and a box
  that is missed must be missed three times over two minutes.

## Gate identity

Controller-side only: `durable/executor.py`, `durable/policy.py`, `durable/engine.py`, `durable/workers.py`. None is a gate dependency or
in `VERDICT_CODE`, and `myident.py` prints identical JSON. It ships with main and a controller restart. Workers and
running cases need no plumbing release.

## Murphy row

- `new-worker-lost-blip-1`: "One `boat list` that misses a live box makes the executor call the worker lost while it
  answers polls. The retry is refused `attempt_busy`, the diagnosis is too, and the hold deletes the box under the
  running G10 (cb5e26 11-19 and 11-20 08:50, 1108c 11-20 01:52; the whole grant booked as waste)." Closed by
  `tests/factory/test_durable_engine_executor.py::InventoryMiss` and
  `test_durable_engine.py::Outcomes.test_a_busy_worker_is_waited_for_on_the_same_box_never_counted_diagnosed_or_released`.

## Deploy (operator)

- Main and a controller restart. Workers are untouched.
- A running attempt that the old controller is polling is reattached by the restarted one.
