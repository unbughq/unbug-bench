# Diff review 1: worker-lost-hysteresis (goldfish)

### Scope

- **Diff:** commit 35f7c49d, on worktree HEAD f0eec9d9, with a clean `git status`. It changes `factory/durable/executor.py`, `policy.py` and `engine.py`, plus `tests/factory/test_durable_engine_executor.py`, `test_durable_engine.py` and `test_durable_engine_fakes.py`.
- **Checked against:**
  - the design, `docs/designs/worker-lost-hysteresis.md`;
  - the Murphy row `new-worker-lost-blip-1` in the local, untracked `docs/murphy-register.md`;
  - the founder's problem statement, as the coordinator gave it.
- **Personas:** `zoom_out` and `implementation_readiness`, Mode: REVIEW, against `implementation-readiness-standard.md` and ENGINEERING §1, §2 and §4.
- **Code read, every place a worker is judged gone or a box is released or deleted:**
  - `executor.py`: `run`, `_cancel_confirm`, `reconcile`, `cancel`, `_alive`, `_retire`, `_silent_and_unrenewed` and the new `_Presence`;
  - `engine.py`: `slot_workflow` (`cancel_step`, then `lease_step`), the retry loop with `pool_wait`, the keep or release branch, `release_worker`, `keeps_worker_for` and the `diagnosis_infra_holds` reference;
  - `workers.py`: `acquire`, `release`, `alive`, `_inventory`, `_find`, `recover` and `sweep`;
  - `runtime.py`: the start path (`recover`, `_sweep_pool`, `SWEEP_INTERVAL_S = 300`);
  - `channel.py`: `BoatChannel.poll` and `cancel`;
  - `contract.py`: `UNANSWERED`, `Poll`, `poll_from_record`, `WorkerChannel` and `WorkerPool`;
  - `worker_step.py`: `start`, `busy` and `poll`;
  - `policy.py`: `deadline_s`, `GATES_DEADLINE_S` and `POOL_WAIT_CEILING_S`;
  - `classify.py`: `WORKER_POOL_REASONS` and `CONTRACT_REASONS`.
- **What I ran:**
  - `tests/factory/test_durable_engine_executor.py`: 46 tests, OK.
  - `Outcomes.test_a_busy_worker_is_waited_for_on_the_same_box_never_counted_diagnosed_or_released`: OK, 24 s.
  - I did not run the full suite. The coordinator says one is already running.

### Requirements check

- **Never lost on one bad read; an answered poll is proof of life. Met in the executor.**
  - `_Presence.gone` returns early on an answered poll and makes no inventory read (`executor.py:404-426`).
  - The main loop, the ABSENT branch, the past-deadline branch, `_cancel_confirm` and `reconcile` all share one tracker per attempt.
- **"Answered" matches the real channel. Met.**
  - `BoatChannel` returns `RUNNING = UNANSWERED` (the identical object) on every transport or parse failure (`channel.py:30`, `:104-137`).
  - `poll_from_record` always builds a new `Poll`, so a worker's own RUNNING answer is never the sentinel.
  - The checkpoint-fetch-failed path returns `Poll(poll.state, poll.result)`. That is a new object, so it counts as answered, which is correct: the worker did answer.
  - The DONE-with-missing-outputs path returns `UNANSWERED`. That only costs one extra inventory read.
- **The test fake matches the real channel. Met.**
  - The fake worker now returns `UNANSWERED` for a dead or dropped poll (`test_durable_engine_fakes.py:500`).
  - The old fresh `Poll(RUNNING)` would read as an answer under the new code, so this change is needed and correct.
- **Dead box still detected within a few minutes. Met.**
  - At a 30 s poll, a deleted box is called lost after about 120 to 150 s.
  - If `boat ssh` to a deleted box hangs until `command_timeout` (120 s) rather than failing fast, the misses spread out to roughly 5 minutes. That is still a few minutes.
- **Replay safety. Met.**
  - `DBOS.patch("attempt_busy_waits")` is only evaluated when the reason is `infra:attempt_busy`. The `or` short-circuit leaves the evaluation of `worker_pool_retry_wait` unchanged.
  - `now_step()` is recorded only under the patch.
  - The new `result.reason != BUSY_REASON` guard comes after the existing `keep_worker_through_waits` patch call, so the order of recorded steps is unchanged.
  - It is reachable only when `pool_wait` is true. For a busy result recorded before the patch, `pool_wait` is false, and the reason is neither a pause nor a late stop, so the branch is never entered on replay.
  - The executor change runs inside `attempt_step`, which is a step, not workflow code.
- **Never release or delete a box while an attempt is live. Partly met.** The engine's busy wait never releases the box. Two gaps remain: findings 1 and 2.

### Findings

#### 1. BLOCKING: the busy wait's 6-hour ceiling is shorter than a GATES attempt's 12-hour deadline, so a busy G10 is counted and diagnosed again

- **Where:** `engine.py:1516-1517`, and the design at `worker-lost-hysteresis.md:51`.
- **What the design claims:** "The orphan ends by its own worker-side deadline. Past the ceiling it counts as infra as before."
- **What the code does:**
  - The busy wait is bounded by `pool_wait_ceiling_s`, which is `POOL_WAIT_CEILING_S = 21_600` (6 h, `policy.py:56`).
  - The orphan is GATES, whose worker-side deadline is `max(step_deadline_s, GATES_DEADLINE_S) = 43_200` (12 h, `policy.py:20` and `:237`).
- **Failure scenario:**
  1. An attempt is lost early in its G10, with up to about 12 h left on the orphan.
  2. After 6 h of waiting, `pool_wait` turns false. Each busy refusal now does `infra += 1` and retries straight away; the nap branch needs `pool_wait`.
  3. A few seconds later the allowance is gone, and the step goes to DIAGNOSE.
  4. The diagnosis is refused busy. It waits up to another 6 h on a fresh `pool_since`.
  5. Then it runs as a paid diagnosis on a healthy case, which may lead to a hold.
- This is the "busy refusals counted → diagnosis" chain that the Murphy row says is closed, on the very step type from the incident (cb5e26 G10). No test covers the ceiling.
- **Fix:** bound a busy wait by the longest step deadline plus grace, not the pool ceiling. For example, in the `pool_wait` recomputation, use `pool_now - pool_since < (max(self.spec.step_deadline_s, GATES_DEADLINE_S) + POLL_GRACE_S if result.reason == BUSY_REASON else _RT.timing.pool_wait_ceiling_s)`. Correct design line 51 to match. Add an engine test where `pool_wait_ceiling_s` is shorter than a scripted busy run, and assert that no diagnosis happens.

#### 2. BLOCKING: the controller's start-up `recover()` still drops a live worker on one inventory read, and this change's own deploy is a controller restart

- **Where:** `workers.py:640-648`, called from `runtime.py:292`.
- **What happens:**
  1. On every controller start, `recover()` reads `_inventory()` once.
  2. If the recorded worker is missing from that one list, it unlinks the case record (`:647`).
  3. The next `sweep()`, within `SWEEP_INTERVAL_S` (300 s), finds the box with no record claiming it and deletes it as a stray (`workers.py:690-701`).
  4. The reattached `attempt_step` is polling that box. Its attempt is one the engine will collect.
  5. After the deletion, `alive()` returns False with no read at all (record is None), and the G10 is lost.
- This is "a live worker lost on one bad inventory read", the founder's exact requirement. The design's deploy section requires a controller restart ("A running attempt ... is reattached by the restarted one"), so each deploy is one exposure per in-flight case.
- **Fix:** delete the unlink when the named worker is simply absent from the list. In `recover`, when `worker is None` and no row has `record["worker"]`'s id, `continue` and keep the record. Keeping a record for a box that is really gone is harmless:
  - `acquire` rewrites it on the next lease (`:536-544`);
  - the executor's `_Presence` calls it lost after its window;
  - `sweep` has no row to delete.

  Keep the existing delete for a row that is present in a dead state; that is a positive observation, not a miss. Add a test in `test_durable_workers.py` that uses the real `tests/factory/fixtures/isolation-timeouts/list.json` with the box removed. Add a new Murphy row, or extend this one.

#### 3. NIT: inside the busy wait, each retry's `lease_step` → `acquire` makes one inventory read, so the wait is not guaranteed to stay "on the same worker"

- **Where:** `workers.py:532-544`, reached through `engine.py:1035`.
- **What happens:**
  - Every busy retry calls `acquire`. With `pause_retry_s` at 900 s, that is about 24 to 48 reads per orphan.
  - On one miss, `acquire` wipes the record and creates or takes a new box. If the row is present in a dead state, it deletes the box outright.
  - The orphan's box becomes a stray, and `sweep` deletes it.
- **Why only a nit:** the orphan's result is never collected. Its attempt was settled lost, and later attempts never poll its key. So nothing the engine uses is lost; the G10 just restarts sooner on a fresh box.
- It still contradicts the design's "naps on the same worker" (line 46) and the founder's literal "never delete a box while a worker-side attempt is live".
- **Suggestion:** state this in the design, or reuse the fix from finding 2 so that `acquire` raises `infra:inventory_unavailable` (already a `WORKER_POOL_REASONS` wait) when a recorded worker is merely missing.

#### 4. NIT (zoom-out): the busy wait waits for work nobody will collect

- After a false loss, the orphan keeps running from the old snapshot. When it ends, its outputs are discarded, and the retry reruns G10 from that same snapshot. So the worst case is about 12 h of waiting followed by a full rerun.
- The founder's rule ("busy is proof of life") is honoured. With the hysteresis in place, busy should be rare.
- Two options for the founder if busy waits are seen in practice:
  - have the retry adopt the orphan's DONE result through the worker's case index (`_index`);
  - or have it cancel the orphan, which is not a deletion.

#### 5. NIT (process): the Murphy row is marked closed by seam-level tests only

- ENGINEERING §2 says a row is closed only by a test that uses real artifacts.
- The design (line 81) and the register row both say honestly that no saved `boat list` output from 08:50 exists.
- **Suggestion:** drive `_Presence` through the real `BoatPool.alive` and `_inventory` code, using the real `tests/factory/fixtures/isolation-timeouts/list.json`, with the box dropped from one read. That exercises the real parsing and `_find`, not just the `pool.alive` seam. Until then, label the row "closed (seam-level)".

#### 6. NIT: `pool.alive` returning False without any read now also waits 3 misses over 120 s

- **Where:** `workers.py:611`.
- When the case has no record, or the record names a different worker, `alive` returns False without a `boat list`. That is a definite answer, not a blip, but `_Presence` now waits out its window on it too.
- The cost is about 2 minutes, and only on a box the pool no longer claims. Acceptable. A one-line comment in `_Presence` would stop a later reader treating it as a bug.

### Verdict

**FAIL.** Two blocking findings are open:

- **Finding 1:** the busy-wait ceiling is shorter than the GATES deadline, so the counted, diagnosed chain comes back for long G10 orphans.
- **Finding 2:** `recover()` still drops a live worker on one inventory read at controller restart, which this change's own deploy triggers.

Both fixes are small: change one bound for finding 1, and delete one unlink for finding 2. Each needs a test. The executor hysteresis, the channel and fake behaviour, and the replay safety of the engine patch are sound. The elephant's full suite is still the merge condition; I did not see it.

## Elephant response

- Finding 1 (BLOCKING, busy-wait ceiling): fixed. A busy wait is bounded by `max(step_deadline_s, GATES_DEADLINE_S) + POLL_GRACE_S`, not `pool_wait_ceiling_s`. The busy engine test now runs with `pool_wait_ceiling_s` 0.1 s and still seals with no diagnosis.
- Finding 2 (BLOCKING, `recover` drops a live worker on one read): fixed. `recover` keeps a record whose worker is merely missing from the list; a present row it cannot adopt is still deleted. New test `test_durable_workers.py::PoolTests.test_restart_keeps_a_recorded_worker_that_one_list_missed` on the real saved list envelope (fails on the old `recover`).
- Nit 3 (`acquire` single read inside the busy wait): documented in the design, not changed. Making `acquire` wait on a miss would leave a case stuck on a truly dead box; the orphan's result is never collected, so nothing the engine uses is lost.
- Nit 4 (waiting for uncollected work): noted for the founder; no change.
- Nit 5 (seam-level row): the new restart test uses the real saved `boat list` envelope; the row states that the miss itself is staged.
- Nit 6 (`alive` False without a read): documented in the design.
- Also found while running the full suite: the engine fakes reported `attempt_busy` across boxes, unlike `worker_step.busy` (box-local). With the busy wait this made `test_failure_drill.py`'s deleted-worker drill nap 900 s. The fake now scopes busy to the box.
