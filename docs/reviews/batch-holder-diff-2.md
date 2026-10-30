**PASS.** No blocker is left open. Each diff-1 blocker and major is genuinely fixed and each fix has a test that fails if reverted. I found one new major (a tight respawn loop for failing orphan resumes) and a handful of nits. I did not run the test suite (another process owns it in this checkout); I could not verify the new ShellWiringTests actually pass at HEAD — the only recorded full-suite evidence in the branch is `docs/reviews/batch-holder-full-4281f83.json`, which predates commit be33db6 and its 339 test lines. Merge must wait for the in-flight run to be green.

## Blockers

None.

## Majors

**M1. A persistently failing orphan resume is respawned every tick, forever.** (`factory/key_holder.py:427-449`, `factory/batch_holder.py:346-360, 363-381`).
- `batch_tick` applies the 60 s `waits` backoff only when a child exits `TEMPFAIL` (`key_holder.py:441`). Resume children run `launch.sh` through `resume_controller`, and `launch.sh` never exits 75, so a resume that fails (bad restore, corrupt monitor state, signing unavailable) is reaped, deleted from `children`, and re-listed by `orphaned()` on the very next tick, because a failed resume leaves no persistent marker (`complete` only appears on success).
- Result: about one `batch_holder.py resume` subprocess per second for the rest of the holder lifetime, per broken orphan. Log spam, PID churn, repeated process spawns that never change the outcome.
- Suggested fix: on a non-TEMPFAIL resume exit, set `waits[operation] = now + 60` exactly like the TEMPFAIL branch, or have `resume_controller` return `TEMPFAIL` for transient refusals. One test: an orphan resume whose `launch.sh` exits 1 immediately must not be spawned twice within the wait window.
- Not blocking: the lifestyle stays fail-closed, the holder survives, and the gate is off in production.

## Nits

- **N1.** `waits` entries are never removed (`key_holder.py:441, 449`). Bounded by operation count; harmless. `waits.pop(operation)` on respawn would keep it tidy.
- **N2.** `record_exit` stores `dispatch_exit=75` for a started operation (`batch_holder.py:246-249`). Combined with the precreation predicate in `_reconcile_one` (`batch_holder.py:299-307`), a started operation whose child exits 75 with a matching `launch.json` and no worker IDs would be marked failed/preflight_refused. Unreachable today because `launch.sh` has no exit-75 path, but the intent only covers unstarted operations; a one-line comment or a `dispatch_started and code == TEMPFAIL` guard would pin it.
- **N3.** `active` counts failed operations (`batch_status.py:227`), and two entries make the row unreadable. It works only because a failed operation consumes its deterministic source, so no second unresolved operation for the same job can exist. Filtering failed ops (or a comment naming that invariant) would make the "unique nonretired" rule robust.
- **N4.** `test_serve_refuses_a_policy_the_shell_commands_would_not_load` covers only the refusal; nothing asserts serve *accepts* the control-home policy path with the gate on.
- **N5.** The direct B1 crash test (`test_batch_tick_never_stops_and_records_only_dispatch_exits`) exercises `batch_tick` with doubled scans, not the real scan functions inside the accept loop. Acceptable — the per-operation reconcile isolation has its own real test (`test_reconcile_isolates_a_refused_operation`) — but a corrupt `money.json` reaching the real `reconcile` from `batch_tick` is only proven by the doubles.

## What holds

- **B1 fixed.** `batch_tick` is one module function with per-phase catches (`key_holder.py:427-449`); a raising operation, scan, spawn or exit record is labelled and retried next tick. `reconcile` isolates each operation through `_reconcile_one` with deep-copy rollback of both the operation and the whole money state (`batch_holder.py:323-343`). `money.json` cannot be left half-written for a failed operation: `atomic_json` is temp+fsync+rename (`registry.py:18-32`), the only write happens before the single non-raising statement, and the crash-between-money-and-reservations window self-repairs on the next tick (tested by `test_retirement_crash_between_money_and_reservations_repairs`). Both isolation tests fail if the catches or the rollback are reverted.
- **B2 fixed and real.** `ShellWiringTests` run the actual `collect.sh`, the actual `collect_vm` and restore snippets extracted from `launch.sh`, the real `transfer.py`/`collection.py` verifiers and the real `bin/r2-presign` as subprocesses. The doubles sit only at the process boundary: the gate constant, root/control-home, `policy_load`, `batch.verify`, the object store behind `urlopen`, and the worker behind `boat-call`. The R2 account/bucket assertions prove the launcher's R2 environment reaches the real signing script. `test_socket_routes_*`, `test_serve_refuses_*`, `test_enabled_bind_*` cover the socket reply/refusal/fall-through and the policy-path gate. Each fails when its wiring is reverted.
- **M1-M5 fixed.** Blocking shared locks on `lookup`/`source_directory` with status the only nonblocking reader; TEMPFAIL keeps transient preflight pending (including a peer's accounting freeze) with a tested 60 s wait; incidents use `setdefault`; `collect.sh` reports publication refusal on its own line, exits with the collection status, and keeps the verified bytes for replay; the matrix gaps (overlap with one creator, ambiguous creation records, positive-refusal no-retry, malformed reservations, publication crash before/during PUT, interrupted PUT, failed and accounting-refused status phases) all have named tests.
- **No new defect in the four inspected fix spots.** The TEMPFAIL path cannot turn a transient refusal into a permanent failure for unstarted operations; started-operation exit 75 is unreachable (see N2). The serve policy check compares resolved paths on both sides and only argues when the gate is on. The `UNBUG_LAUNCH_STATE` check in `batch_holder.py` collect is fail-closed and identical for the original and resumed controller. `collect.sh` exiting 0 on publication refusal matches the reviewed decision — retirement still needs both deletion receipts, and the refused op can never advance source.
- **Design/scope holds.** Every file in the design's contract is touched and nothing beyond it: no diagnosis dispatch, no live test, no activation, no cross-batch carry-over, legacy cases default to retire, cb5e2/14d35 untouched, `HOLDER_ENABLED=False` is a code constant that no runtime input can flip, and each hold depends on it. The addenda in `batch-service.md` and `status.md` are satisfied by the shared journal validator, the overlay status and the pointer/money/ACK sequence. No Murphy row is closed and `docs/murphy-register.md` is untouched. No scope creep; the review-record files are required flow artifacts.

Reviewer scope: read-only; no test run (suite is in flight elsewhere), so be33db6's tests are unverified by me. Risk: merge must follow a green full-suite run at HEAD, since the recorded evidence stops at 4281f83.

---

Reviewer: goldfish, OpenCode `openrouter/~deepseek/deepseek-pro-latest` (variant max), via T3 delegate_task, 2026-10-30. Personas: zoom_out, implementation_readiness. Mode: REVIEW. Range: `4f291fb..82b70ee`.

## Elephant response

- **Suite.** The in-flight full suite finished green at `82b70ee`: 155 test scripts run, 0 failed. Record: `batch-holder-full-82b70ee.json` and `.log.gz`.
- **M1 accepted, not fixed in this increment.** I did not change code after this review, so the reviewed diff and the green suite stay the same SHA. The respawn loop can only happen with `HOLDER_ENABLED=True`, which this increment never turns on. The fix (a 60 s wait after any non-zero resume exit, plus the one-spawn-per-window test) is the first item for the activation increment.
- **Nits N1–N5** are optional and stay open. N2 and N4 go with the M1 fix.
- No finding is rejected. No Murphy row is closed.
