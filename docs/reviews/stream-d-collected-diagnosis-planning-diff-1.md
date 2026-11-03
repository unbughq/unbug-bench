## Goldfish DIFF review, round 1 of 2: `b80929a..986d788` (implementation `3e35280`)

**Code verdict: NOT PASS.** There is one Major finding, and it is in the tests, not the production code. The three production files match design-2 as accepted. One test guard can never fail. Fixing it takes about three lines in the test file. No production change is needed.

### Production code (holder, service, key_holder): no findings

- **Scope.** Only `factory/batch_holder.py`, `factory/batch_service.py` and `factory/key_holder.py` change. There is no schema, grant, router, config, launcher, manifest or activation change. `plan_collections` returns `[]` and never reserves, dispatches or spawns.
- **Shared `_post` prefix.** `_current_operation` at `batch_holder.py:171` is the old `_post` prefix moved unchanged. It checks the export marker, money incidents, the aggregate limit, the deadline, job overrun, authority, last source and the frozen config. `_post` calls it and keeps its source checks unchanged.
- **In-lock checks.** `_planning_source` at `batch_holder.py:197` runs inside `plan`'s single existing money lock. In order, it checks:
  - the holder is enabled and the diagnosis policy is on;
  - the operation passes `_current_operation`;
  - the operation is `launched`, has no incident, has a retirement, and its case and output generation match;
  - no successor operation exists;
  - `_source` passes: ACK, current pointer, acknowledged outbox, retirement matches ACK, authority, immutable snapshot and `job_money`;
  - the returned entry's case and generation match.

  All of this happens before `retire_legacy`, projection or the journal write.
- **Successor sources.** `row['sources'][-1] == op['source_generation']` stays valid after collection, because sources are only appended at successor reserve (`batch_money.py:369`).
- **One snapshot per attempt.** On the production path `_snapshot` is called once, through `_source → _entry`, and `plan` reuses that card. Plain local `plan` keeps the old `_snapshot` call. The function-local import avoids the import cycle.
- **Lock depth.** The scan lock is released before `service.plan` is called, so there is no nested `flock`.
- **Skips.** The cheap scan skips operations that are not launched, have an incident, have no retirement, have no output, or have a successor. It also skips entries whose facts are already set and generations with an existing or symlinked retirement marker (`batch_holder.py:503`).
- **Retry.** The retry delay is process-local and keyed by (home, manifest SHA, case, generation). A failure sets 60 s from `time.monotonic()`. A success removes the key, and a restart clears the map. It catches the same five exception types as `schedule_waits`. `MoneyWait` is a subclass of `ValueError`, so it is caught per candidate. An export marker is raised from `money.locked` outside the loop and becomes the existing `batch scan refused` label.
- **Tick wiring.** `key_holder.py:463` places `plan_collections` after `reconcile` and before `schedule_waits`, with action `None`.

### Test findings (`tests/factory/test_batch_planning.py`)

1. **Major: the tick's no-reserve/dispatch/spawn guards can never fail.**
   - **Where:** `PlanningTests.tick()`, used by `test_tick_plans_once_without_reservation_or_money_mutation`, `test_legacy_retirement_is_not_rehashed` and `test_refusal_backoff_is_bounded_and_not_an_auth_cache`.
   - **Evidence:** `reserve`/`dispatch` are patched with `side_effect=AssertionError`, and spawn is `lambda *a: self.fail(...)`. All of these run inside `key_holder.batch_tick`. Its scans sit inside `except Exception: print('batch scan refused')` and its spawns inside `except Exception: print('batch child refused')` (`key_holder.py:467-472`). `AssertionError` is a subclass of `Exception`, so an unwanted call would be swallowed and printed, and the test would still pass. The design's midterm explicitly requires "never calls reserve/dispatch/spawn". Unchanged `money.json`/`reservations.json` bytes cover reserve writes indirectly, but nothing covers spawn or dispatch.
   - **Fix:** use the existing pattern at `test_batch_holder.py:477`. Make spawn a recorder (`spawned = []`, `lambda op, action: spawned.append((op, action)) or op`). Use `patch.object(holder, 'reserve') as reserve` and `patch.object(holder, 'dispatch') as dispatch`. After each tick, assert `spawned == []`, `reserve.assert_not_called()` and `dispatch.assert_not_called()`.

2. **Nit: the lock-depth test never runs `plan_collections → plan` under the counter.**
   - **Where:** `test_lock_depth_never_exceeds_one`.
   - **Evidence:** the direct `service.plan` call commits facts first. The following `self.scan()` then skips the entry at the cheap `entry['facts'] is not None` check, so the scan path only takes the scan lock. Other real-tick tests would hang on a nested `flock`, which gives implicit coverage, but this test does not prove what the design asks of it.
   - **Fix:** call `self.scan()` first, which plans through `plan_collections → plan`. Then call `service.plan(..., published_operation=...)` directly; it re-authenticates and returns `planned`. Optionally assert `len(self.state()['queue']) == 1` between the two calls.

3. **Nit: the money, export and consumed-source matrix doesn't compare journal bytes.**
   - **Where:** `test_money_export_and_consumed_source_refuse`.
   - **Evidence:** the design says "Assert no projection/journal write". The sibling proof-matrix test compares `journal.json` bytes, but this one only checks `assert_unplanned()` and the protected files. The `_snapshot` `AssertionError` guard covers most of the gap.
   - **Fix:** capture `journal = (self.directory / 'journal.json').read_bytes()` after `before = self.protected()`, and assert it is unchanged at the end, as the proof-matrix test does.

**Test labelling is honest.** The module docstring and `setUp` state that the controls are retained ciphertext, a saved card and creation event, authored bindings and deletion proofs, and a diagnosis API double. They claim no real eligibility, live qualification or Murphy closure. The pipeline below the tick is real: reserve, start, output, publish, retirement, reconcile and plan. Other requirements are met:
- The only holder-file change is the one approved line in `test_tick_future_due_restart_and_single_successor`.
- The retry map is cleared in `setUp` through `patch.dict`.
- `monotonic` is patched only inside the block that runs the ticks.
- The negative matrix, the two-job peer case, the pointer change between selection and lock, the commit crash before and after publication, and late publication/retirement are all present.

### Delivery evidence (separate from the code verdict)

- **Full suite at `3e35280`:** 185 scripts, 1 failed (184 passed), exit 1. The committed log and JSON record (`…-20261103T174906Z-80c52ba9`) agree. In that run planning passed 11/11 and holder passed 60/60.
- **The failing file:** only `tests/factory/test_control_resume.py`, with 5 failures. I confirmed that this test, `factory/control_resume.py` and `factory/launch.sh` are unchanged in `b80929a..986d788`. The first failure's message is `controller did not reach after-handoff-reserved: launch abandoned`. I did not check whether the 10/20 s deadline actually caused it.
- **Focused recheck:** still running and incomplete (645 bytes when I read it). Its progress lines already show failures (`FF...F.F` and `FF.FF.F.......`). It has not shown a pass. The suite should not be relabelled 185/0, and the controller failures should not be accepted as load-only until the elephant commits the finished result.
- **Report:** `docs/reports/stream-d-collected-diagnosis-planning.md` correctly says "Fresh diff review: pending" and reports 185/1.

### Skipped checks

Per the brief, I ran no tests, full suite or focused recheck, and made no edits, commits, network or model calls. I also did not:
- re-review earlier increments (the opt-in and the parallel-tests runner);
- read the design-1/design-2 review records beyond the design doc and the implementation report's summary of them;
- read the full `_project`/`_enqueue` body, beyond the lines that show the `resume/<case>/<generation>` key comes from a pending projection.

The worktree's only untracked file is the active recheck log, and there are no implementation edits.

## Elephant disposition

All findings accepted. Replace swallowed exception guards with recorder/mock
assertions outside batch_tick, exercise scan-to-plan before direct plan in lock
test, and compare journal bytes in the money matrix. No production change.
Controller recheck completed with nine failures, but omitted BENCH unlike the
suite; runner_supervisor uses BENCH for bin imports. Record this mistake and
repeat only that focused file with the suite environment. No repeat full suite.

