# Diff review 2: worker-lost-hysteresis (goldfish)

**Verdict: PASS.** Both blocking findings from review 1 are fixed, and the tests that would fail without the fixes now pass. I found no new blocking problems. Five optional nits are listed below.

### Scope

- **Diff:** commits 35f7c49d and 19647dad, reviewed as one change. Worktree HEAD is 14d512bd and `git status` is clean. The interleaved credit-wake commits 235849f9, 97250377 and 14d512bd are not in scope.
  - **Code:** `factory/durable/executor.py`, `policy.py`, `engine.py`, `workers.py`.
  - **Tests:** `tests/factory/test_durable_engine_executor.py`, `test_durable_engine.py`, `test_durable_engine_fakes.py`, `test_durable_workers.py`.
- **Checked against:**
  - the design, `docs/designs/worker-lost-hysteresis.md`;
  - review 1 and the author's responses, `docs/reviews/worker-lost-hysteresis-diff-1.md`;
  - the Murphy row `new-worker-lost-blip-1`;
  - the founder's problem statement.
- **Personas and standards:** `zoom_out` and `implementation_readiness`, Mode: REVIEW, against `implementation-readiness-standard.md` and ENGINEERING §1, §2 and §4.
- **Code read:**
  - `executor.py`: `run`, `_poll`, `_silent_and_unrenewed`, `_retire`, `_alive`, `_cancel_confirm`, `reconcile`, `cancel`, `_Presence`.
  - `engine.py`: the step functions around `slot_workflow` (`cancel_step` → `lease_step` → `attempt_step`), the `run_seq` retry loop (`pool_wait`, the ceiling, the infra count, the operational-wait branch, the RETRY nap and release), `keeps_worker_for`, `KEEP_WORKER_WAIT_S`.
  - `workers.py`: `acquire`, `release`, `alive`, `recover`, `sweep`, `_inventory`, `_find`, `_delete_locked`, `_delete_raw`.
  - Other: `channel.py` `BoatChannel.poll`; `contract.py` `UNANSWERED`; `worker_step.py` `start`, `busy`, `poll`, `cancel`, `supervise`; `policy.py` `deadline_s` and constants; `classify.py` `WORKER_POOL_REASONS`; `runtime.py` `launch` and the `renewing` wiring; the other `_records()` readers (`backup.py`, `helper_link.release_orphans`); `checkpoints.py` `VERDICT_CODE`.
- **What I ran:**
  - `tests/factory/test_durable_engine_executor.py`: 46 tests, OK.
  - `PoolTests.test_restart_keeps_a_recorded_worker_that_one_list_missed` and `PoolTests.test_restart_adopts_recorded_workers_and_deletes_only_this_pools_orphans`: OK.
  - `Outcomes.test_a_busy_worker_is_waited_for_on_the_same_box_never_counted_diagnosed_or_released`: OK, 24 s.
  - I did not run the full suite, because one is already running on the host. I did not revert code to check the design's "failing first" claims. I traced them by hand instead (below).

### Review 1 blocking findings: are they fixed?

- **Finding 1 (the 6 h busy ceiling is shorter than a 12 h GATES attempt): fixed.**
  - A busy wait is now bounded by `max(self.spec.step_deadline_s, GATES_DEADLINE_S) + POLL_GRACE_S` (`engine.py:1518-1520`).
  - `deadline_s()` never returns more than that maximum (`policy.py:234-238`).
  - The worker's supervisor kills the attempt at its own `deadline_s` and allows `KILL_GRACE_S` for it to exit (`worker_step.py:445-468`). The busy wait's clock (`pool_since`) starts after the orphan started. So the orphan is no longer busy before the ceiling runs out.
  - The test now sets `pool_wait_ceiling_s: 0.1` with `pause_retry_s: 0.2`. Under the old ceiling, the second busy result would count (infra = 1, retried at once with no nap) and the third would go to DIAGNOSE, so the assertion that the case seals would fail. The test therefore proves the fix.
  - Replay is unaffected: the ceiling is pure arithmetic, and it is reached only when `pool_wait` is true, which for a busy result requires the `attempt_busy_waits` patch.
- **Finding 2 (`recover()` drops a live worker on one inventory read): fixed.**
  - If a record's worker id is simply missing from the list, `recover` now keeps the record (`workers.py:644-648`).
  - If the box is in the list but cannot be adopted (dead state), it is still deleted and its record unlinked, as before.
  - In the new restart test, the old code would unlink the record. The next `sweep` would then delete the box as a stray, and the `inventory == [bx_d6dzvjbc]` assertion would fail. The test proves the fix, and it reads through the real saved `list.json` envelope.
  - I checked the other places that read pool records for side effects of a kept record:
    - `sweep` keeps it, because the record still claims the box.
    - `acquire` rewrites it on the next lease.
    - `helper_link.release_orphans` now releases a missed helper box directly instead of leaving it for `sweep`. The outcome is the same, and `_delete_raw` handles an absent box by writing an `absent` completion receipt.
    - `backup.reconcile` does not count it as uncertain.
    - The restored-launch path is untouched.

### Requirements check

- **Never lose a live worker on one bad read: met.**
  - Any answered poll is proof of life and needs no inventory read (`executor.py:417`).
  - A worker is gone only after 3 misses in a row that span at least 120 s.
  - One tracker covers the whole attempt: the main loop, the ABSENT branch, the past-deadline branch, `_cancel_confirm` and `reconcile`.
  - `cancel` keeps one read, as the design says. The `_Presence(misses=1, window_s=0)` default reproduces the old behaviour, except that an answered poll is no longer overruled by an inventory read.
- **`infra:attempt_busy` is proof of life: met in the engine.**
  - A busy result is never counted, so it cannot reach a diagnosis or the hold.
  - The RETRY nap never releases the box for a busy result (`engine.py:1586-1588`). This guard comes after the existing `keep_worker_through_waits` patch call, so the order of recorded steps is unchanged.
  - The remaining paths that delete a box under a live orphan all go through the retry's own `acquire`:
    - a single inventory miss (documented in the design);
    - a bench mismatch, which deletes the box;
    - four consecutive `credentials_unavailable` results, which trigger `release_worker`.
  - None of these loses anything the engine collects, because the orphan's result was already settled as lost.
- **"Answered" matches the real channel: met.** `BoatChannel.poll` is the only production channel, and every transport or parse failure returns the shared `UNANSWERED` object. The fake worker now does the same, and both run in one process, so the object comparison holds.
- **A dead box is still detected within a few minutes: met.**
  - At the 30 s poll, misses fall at 0, 30, 60, 90 and 120 s, so the loss is called at about 120-150 s.
  - The test bounds this at 120-180 s, and also covers a 90 s poll (exactly 3 misses, 180 s).
- **Replay safety: met.**
  - `DBOS.patch("attempt_busy_waits")` is evaluated only for a busy result. It is not evaluated for a `WORKER_POOL_REASONS` result, because the `or` short-circuits after `worker_pool_retry_wait`.
  - `now_step()` is recorded only under the patch.
  - The executor runs inside `attempt_step`, which is a step.
  - The recover and executor changes are control-side code, not workflow code.
- **Gate identity: met.** None of the touched files is in `BENCH_VERDICT_CODE` or `MODEL_CODE` (`checkpoints.py:130-133`). `calibration.py`, `gate_state.py` and `bin/claims.py` are untouched.

### Findings

#### 1. NIT: an unreadable inventory resets the miss count, so a flaky `boat list` can slow dead-box detection to the 30-minute backstop

- **Where:** `executor.py:417`, with `_alive` at `executor.py:222-226` and `BoatPool.alive` at `workers.py:617`.
- **What happens:** `BoatPool.alive` answers True on a `PoolError` ("unknown is never dead"). `_Presence.gone` treats that True as a find and resets `first_miss` and `misses`. The design says "A find resets the count". An unknown read was meant to neither count nor reset.
- **Failure scenario:** a dead box while `boat list` returns `inventory_unavailable` on at least one read in every five. At the 30 s poll the 120 s window never fills.
- **Why only a nit:** the loss is still caught by `_silent_and_unrenewed`, because the guard's `renewing` answers False for a dead box after `SILENT_WORKER_LIMIT_S` (1800 s, wired in `runtime.py:235`). So the delay is bounded at about 30 minutes, not hours.
- **Fix (optional):** say this in the design and in the `_Presence` docstring. Alternatively, have `_Presence` catch the pool's exception itself, so that unknown leaves the count alone. That means calling `pool.alive` directly instead of `_alive`, and it only works for pools that raise rather than swallow the error, so `BoatPool.alive` would need to re-raise `PoolError`. That is a contract change, and probably not worth making now.

#### 2. NIT: no test exercises the "never release a busy worker" guard

- **Where:** `engine.py:1588`; test at `test_durable_engine.py:272-281`.
- **Why the test passes anyway:**
  - The test leaves `release_worker_after_sleep_s` at its 1800 s default.
  - With that default, `keeps_worker_for(0.2)` is already True, because `KEEP_WORKER_WAIT_S` is 21 600 s.
  - So the "released only at the end" assertion passes even with the `result.reason != BUSY_REASON` guard removed.
  - Production has the same default and `pause_retry_s` is 900 s, so in production the guard is a backstop. The design states it as a property ("even when a batch sets a short `release_worker_after_sleep_s`").
- **Fix:** add `"release_worker_after_sleep_s": 0.1` to the first arm's `spec` in the busy test.

#### 3. NIT: a pool-reason result late in a long busy wait is measured against the 6 h pool ceiling

- **Where:** `engine.py:1512-1520`.
- **What happens:**
  - `pool_since` is shared by busy results and `WORKER_POOL_REASONS` results.
  - Suppose the busy wait has already lasted more than 6 h. A busy retry's own `acquire` then returns, say, `infra:inventory_unavailable`.
  - That result is checked against `pool_wait_ceiling_s` from the busy wait's start, so it counts against the allowance at once, with no nap.
  - After `max_infra_retries_per_step + 1` such results the step goes to DIAGNOSE while the orphan may still be live.
  - The diagnosis's own start is refused busy and waits under the new bound, so no box is deleted. The cost is a paid diagnosis on a healthy case.
- **Why only a nit:** this needs a busy wait of more than 6 h (a G10 lost in its first half) plus several pool failures in its tail.
- **Fix (optional):** reset `pool_since` when the reason moves between the busy class and the pool class, or keep a separate `busy_since`.

#### 4. NIT: one subtest proves nothing beyond its neighbour

- **Where:** `test_durable_engine_executor.py:503`.
- **What happens:** with an answering worker the pool is never read, so `Blinks(range(1, 1000))` (labelled "a record that never matches") behaves exactly like `Blinks({1})`. Both subtests prove that no read is made, which is useful. The label suggests more coverage than there is.
- **Fix:** drop the second pool, or relabel it, for example "any inventory, never read".

#### 5. NIT (process, carried from review 1, nit 5): the main path is closed by seam-level tests

- **What is real and what is not:**
  - The executor tests (`InventoryMiss`) stage the miss at the `pool.alive` seam.
  - Only the restart test goes through real `BoatPool` parsing of the saved `list.json` envelope.
- **Why only a nit:** ENGINEERING §2 asks for real artifacts, and the row honestly says the miss itself is staged. The executor's decision does not depend on why the read missed, so I agree this is a nit.
- **Fix (optional):** add one test that drives `Executor.run` against a real `BoatPool` on the `test_durable_workers.py` harness, with `inventory.json` emptied for a single read while the stand-in worker answers polls. That would make the row's real-artifact claim complete.

### Verdict

**PASS.** No blocking finding is open.

- **Review 1, finding 1:** fixed, and the reworked test proves it.
- **Review 1, finding 2:** fixed, with a failing-first test on the real list envelope.
- **Review 1 nits 3-6:** dispositions are recorded in the design and are acceptable.
- **This review's findings 1-5:** all optional. Finding 2 is a one-line test change and is the most worth doing.

The elephant's full suite on this exact head is still the merge condition. I did not see its result.

## Elephant response

- Nit 1 (an unreadable inventory resets the count): not changed. "Unknown is never dead" is the pool contract; the silent-and-unrenewed retirement bounds the delay at about 30 minutes, as the review says.
- Nit 2 (the release guard untested): fixed. The busy test's first arm sets `release_worker_after_sleep_s` 0.1, so only the busy guard keeps the worker; the test fails with the guard removed.
- Nit 3 (shared `pool_since`): not changed; it needs a busy wait over 6 h plus pool failures in its tail, and no box is deleted.
- Nit 4 (subtest label): not changed.
- Nit 5 (seam-level executor tests): not changed; recorded in the Murphy row.
